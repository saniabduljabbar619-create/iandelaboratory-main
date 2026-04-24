# -*- coding: utf-8 -*-
from sqlalchemy.orm import Session
from fastapi import HTTPException
from sqlalchemy import func
from datetime import datetime

from app.models.cashier_referral import ReferralStore, ReferralData, ReferralFinancialRecord
from app.models.test_type import TestType
from app.models.test_request import TestRequest
from app.models.payment import Payment
from app.schemas.cashier_referral import CashierReferralSyncRequest
from app.schemas.patient import PatientCreate
from app.services.patient_service import PatientService

class CashierReferralService:
    @staticmethod
    def sync_and_convert(db: Session, data: CashierReferralSyncRequest, current_user):
        p_service = PatientService(db, current_user)
        
        # 🛡️ THE SUPER-ADMIN SHIELD
        # If the user has no branch_id (Super Admin), default to Branch 1 (Head Office)
        effective_branch_id = current_user.branch_id if current_user.branch_id else 1
        
        try:
            # --- PHASE 1: GENERATE UNIFIED BATCH CODE ---
            timestamp = datetime.now().strftime("%y%m%d-%H%M%S")
            batch_code = f"REF-{effective_branch_id}-{timestamp}"
            
            total_gross = 0.0
            all_request_ids = []

            # --- PHASE 2: PROCESSING PATIENTS ---
            for p_entry in data.patients:
                # 1. Record the Intent (Archive)
                store_entry = ReferralStore(
                    batch_code=batch_code,
                    facility_name=data.facility_name,
                    facility_phone=data.facility_phone,
                    facility_address=data.facility_address,
                    clinician_name=data.clinician_name,
                    patient_name_snapshot=p_entry.full_name,
                    patient_phone_snapshot=p_entry.phone,
                    test_types_csv=",".join(map(str, p_entry.test_type_ids)),
                    sample_type=p_entry.sample_type,
                    branch_id=effective_branch_id
                )
                db.add(store_entry)
                db.flush()

                # 2. Create Clinical Identity (Standardized via Service)
                patient_obj = p_service.create(PatientCreate(
                    full_name=p_entry.full_name,
                    phone=p_entry.phone,
                    gender=p_entry.gender,
                    date_of_birth=p_entry.dob,
                    branch_id=effective_branch_id
                ))

                # 3. Create Requests
                last_req_id = None
                for t_id in p_entry.test_type_ids:
                    tt = db.query(TestType).filter(TestType.id == t_id).first()
                    if not tt: continue
                    
                    total_gross += float(tt.price)
                    req = TestRequest(
                        patient_id=patient_obj.id,
                        test_type_id=t_id,
                        status="paid",
                        requested_by=data.clinician_name,
                        branch_id=effective_branch_id
                    )
                    db.add(req)
                    db.flush()
                    all_request_ids.append(req.id)
                    last_req_id = req.id

                # 4. Create the Bridge
                db.add(ReferralData(
                    store_id=store_entry.id,
                    patient_id=patient_obj.id,
                    test_request_id=last_req_id,
                    status="converted"
                ))

            # --- PHASE 3: FINANCIAL AUTHORITY ---
            net_amount = total_gross * (1 - (data.financials.discount_percent / 100))

            # Record Payment (Main Lab Ledger)
            pay = Payment(
                patient_id=None,
                amount=net_amount,
                method=data.financials.payment_method,
                status="completed",
                notes=f"BATCH:{batch_code}",
                branch_id=effective_branch_id,
                created_by_id=current_user.id,
                request_ids_csv=",".join(map(str, all_request_ids))
            )
            db.add(pay)
            db.flush()

            # Record Ledger (Referrer Ledger)
            db.add(ReferralFinancialRecord(
                batch_code=batch_code,
                referrer_id=data.referrer_id,
                gross_total=total_gross,
                discount_percent=data.financials.discount_percent,
                net_payable=net_amount,
                payment_id=pay.id,
                is_settled=False
            ))

            db.commit() # 🔒 FINAL AUTHORIZATION
            return {"status": "Success", "batch_code": batch_code}

        except Exception as e:
            db.rollback()
            print(f"CRITICAL SYNC ERROR: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))