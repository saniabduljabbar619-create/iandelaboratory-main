# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.db.session import get_db
from app.api.deps import get_current_user
from app.schemas.cashier_referral import CashierReferralSyncRequest
from app.services.cashier_referral_service import CashierReferralService
from app.models.cashier_referral import ReferralStore, ReferralFinancialRecord

# Models for the dashboard view
from app.models.referrer import Referrer

router = APIRouter()

# ==============================================================
# 1. ATOMIC SYNC (Used by ReferralWizardView._atomic_sync)
# ==============================================================
@router.post("/sync-batch")
def sync_referral_batch(
    data: CashierReferralSyncRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Orchestrates the creation of:
    ReferralStore (Archive) + Patients (Identity) + Ledger (Money)
    """
    return CashierReferralService.sync_and_convert(db, data, current_user)

# ==============================================================
# 2. OBSERVABLE DASHBOARD (Used by ReferrerDashboardDialog._load)
# ==============================================================
@router.get("/dashboard")
def get_referrer_dashboard(referrer_id: int, db: Session = Depends(get_db)):
    """
    Aggregates financial and patient data from the new Sovereign tables.
    """
    # Calculate Total Outstanding (Net Payable from the Ledger)
    total_credit = db.query(func.sum(ReferralFinancialRecord.net_payable))\
                    .filter(ReferralFinancialRecord.referrer_id == referrer_id).scalar() or 0.0

    # Fetch Batches with aggregated patient counts from the Store
    # This is a high-performance query for the enterprise table view
    batches = db.query(
        ReferralFinancialRecord.batch_code,
        ReferralFinancialRecord.net_payable.label("booking_total"),
        ReferralFinancialRecord.gross_total.label("gross"),
        ReferralFinancialRecord.created_at,
        func.count(ReferralStore.id).label("patients_count")
    ).join(ReferralStore, ReferralFinancialRecord.batch_code == ReferralStore.batch_code)\
     .filter(ReferralFinancialRecord.referrer_id == referrer_id)\
     .group_by(ReferralFinancialRecord.batch_code)\
     .order_by(ReferralFinancialRecord.created_at.desc()).all()

    return {
        "total_credit": float(total_credit),
        "bookings": [dict(row._mapping) for row in batches]
    }

# ==============================================================
# 3. BATCH DRILL-DOWN (Used by BookingDetailsDialog._load_details)
# ==============================================================
@router.get("/booking/{booking_code}")
def get_batch_details(booking_code: str, referrer_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the immutable snapshots from the ReferralStore.
    Ensures the Referrer sees exactly what was recorded during intake.
    """
    records = db.query(ReferralStore).filter(
        ReferralStore.batch_code == booking_code
    ).all()
    
    if not records:
        raise HTTPException(status_code=404, detail="Batch snapshot not found")

    return [
        {
            "full_name": r.patient_name_snapshot,
            "phone": r.patient_phone_snapshot,
            "sample_type": r.sample_type,
            "test_names": r.test_types_csv,
            "created_at": r.created_at
        } for r in records
    ]

# ==============================================================
# 4. REFERRER LIST (Used by Wizard Tab 0)
# ==============================================================
@router.get("/list")
def list_referrers(db: Session = Depends(get_db)):
    return db.query(Referrer).all()