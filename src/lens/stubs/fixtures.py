"""Fixture releases hand-cut from real Kenya PPIP shapes (probed 2026-10-11).

Deliberately includes the messiness the challenge promises:
- one record with tenderPeriod.startDate AFTER endDate (mirrors a real release:
  KHWS/OT/09/2026-2027, ocid ocds-vn56pm-b60301c5-9058-4118-a31e-939970e0e4c5)
- one record with a missing buyer name
- one supplier under three alias spellings with inconsistent identifiers
- one obvious price outlier (~5x the comparable median)

Clean-row values/suppliers are synthetic; only the malformed-date row mirrors a
record actually observed at tenders.go.ke. FY keys use the portal's "YYYY/YYYY".
"""

FIXTURE_RELEASES: list[dict] = [
    # --- clean comparables: patient monitors, ~KES 450-510k ---
    {
        "ocid": "ocds-vn56pm-stub-0001", "id": "rel-0001", "date": "2025-08-14T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2025/2026",
        "buyer": {"name": "Ministry of Health"},
        "tender": {
            "title": "Supply and Delivery of Medical Equipment - Patient Monitors",
            "tenderPeriod": {"startDate": "2025-07-10", "endDate": "2025-08-01"},
            "procurementMethod": "open",
            "items": [{"description": "Patient monitor, multiparameter, portable"}],
        },
        "awards": [{
            "id": "awd-0001", "date": "2025-08-14",
            "value": {"amount": 450000, "currency": "KES"},
            "suppliers": [{"name": "MEDTECH SOLUTIONS LTD",
                           "identifier": {"scheme": "KE-PPRA", "id": "KE-1147"}}],
        }],
    },
    {
        "ocid": "ocds-vn56pm-stub-0002", "id": "rel-0002", "date": "2025-09-02T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2025/2026",
        "buyer": {"name": "Kenyatta National Hospital"},
        "tender": {
            "title": "Supply of Patient Monitors (Kisumu lot)",
            "tenderPeriod": {"startDate": "2025-08-05", "endDate": "2025-08-26"},
            "procurementMethod": "open",
            "items": [{"description": "Patient monitor, multiparameter"}],
        },
        "awards": [{
            "id": "awd-0002", "date": "2025-09-02",
            "value": {"amount": 480000, "currency": "KES"},
            "suppliers": [{"name": "Medtech Solutions Ltd.",
                           "identifier": {"scheme": "PPRA", "id": "1147"}}],
        }],
    },
    {
        "ocid": "ocds-vn56pm-stub-0003", "id": "rel-0003", "date": "2025-10-11T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2025/2026",
        "buyer": {"name": "County Government of Nakuru"},
        "tender": {
            "title": "Patient Monitors for Level 4 Facilities",
            "tenderPeriod": {"startDate": "2025-09-15", "endDate": "2025-10-05"},
            "procurementMethod": "open",
            "items": [{"description": "Patient monitor, multiparameter, portable"}],
        },
        "awards": [{
            "id": "awd-0003", "date": "2025-10-11",
            "value": {"amount": 510000, "currency": "KES"},
            "suppliers": [{"name": "MED-TECH SOLUTIONS LIMITED", "identifier": None}],
        }],
    },
    # --- the outlier: same item, 5x median, different supplier ---
    {
        "ocid": "ocds-vn56pm-stub-0004", "id": "rel-0004", "date": "2025-11-20T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2025/2026",
        "buyer": {"name": "Machakos Level 5 Hospital"},
        "tender": {
            "title": "Procurement of Patient Monitors and Accessories",
            "tenderPeriod": {"startDate": "2025-10-20", "endDate": "2025-11-10"},
            "procurementMethod": "open",
            "items": [{"description": "Patient monitor, multiparameter"}],
        },
        "awards": [{
            "id": "awd-0004", "date": "2025-11-20",
            "value": {"amount": 2400000, "currency": "KES"},
            "suppliers": [{"name": "Bluebird Supplies Ltd",
                           "identifier": {"scheme": "KE-PPRA", "id": "KE-3391"}}],
        }],
    },
    # --- malformed dates: mirrors the real release observed 2026-10-11 ---
    {
        "ocid": "ocds-vn56pm-b60301c5-9058-4118-a31e-939970e0e4c5",
        "id": "rel-0005", "date": "2026-09-30T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2026/2027",
        "buyer": {"name": "The Cabinet Secretary Ministry of Health"},
        "tender": {
            "title": "TENDER NO. KHWS/OT/09/2026-2027 FOR SUPPLY AND DELIVERY OF MEDICAL EQUIPMENT: Patient Monitors",
            "tenderPeriod": {"startDate": "2026-09-30", "endDate": "2026-06-03"},  # start AFTER end — real-world mess
            "procurementMethod": "open",
            "items": [{"description": "Patient monitor, multiparameter"}],
        },
        "awards": [{
            "id": "awd-0005", "date": "2026-09-30",
            "value": {"amount": 3500000, "currency": "KES"},
            "suppliers": [{"name": "Healthkit Ltd",
                           "identifier": {"scheme": "KE-PPRA", "id": "KE-2210"}}],
        }],
    },
    # --- missing buyer name ---
    {
        "ocid": "ocds-vn56pm-stub-0006", "id": "rel-0006", "date": "2025-12-01T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2025/2026",
        "buyer": {"name": None},
        "tender": {
            "title": "Supply of Laboratory Reagents",
            "tenderPeriod": {"startDate": "2025-11-01", "endDate": "2025-11-21"},
            "procurementMethod": "open",
            "items": [{"description": "Laboratory reagents, general"}],
        },
        "awards": [{
            "id": "awd-0006", "date": "2025-12-01",
            "value": {"amount": 890000, "currency": "KES"},
            "suppliers": [{"name": "Labcare Ltd",
                           "identifier": {"scheme": "KE-PPRA", "id": "KE-4402"}}],
        }],
    },
    # --- reagents comparables ---
    {
        "ocid": "ocds-vn56pm-stub-0007", "id": "rel-0007", "date": "2025-12-15T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2025/2026",
        "buyer": {"name": "Ministry of Health"},
        "tender": {
            "title": "Supply of Laboratory Reagents (framework call-off)",
            "tenderPeriod": {"startDate": "2025-11-10", "endDate": "2025-12-01"},
            "procurementMethod": "framework",
            "items": [{"description": "Laboratory reagents, general"}],
        },
        "awards": [{
            "id": "awd-0007", "date": "2025-12-15",
            "value": {"amount": 720000, "currency": "KES"},
            "suppliers": [{"name": "SciSupply Ltd",
                           "identifier": {"scheme": "KE-PPRA", "id": "KE-5120"}}],
        }],
    },
    {
        "ocid": "ocds-vn56pm-stub-0008", "id": "rel-0008", "date": "2026-01-20T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2025/2026",
        "buyer": {"name": "County Government of Nakuru"},
        "tender": {
            "title": "Laboratory Reagents for County Referral Hospital",
            "tenderPeriod": {"startDate": "2025-12-10", "endDate": "2026-01-05"},
            "procurementMethod": "open",
            "items": [{"description": "Laboratory reagents, general"}],
        },
        "awards": [{
            "id": "awd-0008", "date": "2026-01-20",
            "value": {"amount": 810000, "currency": "KES"},
            "suppliers": [{"name": "Labcare Ltd",
                           "identifier": {"scheme": "KE-PPRA", "id": "KE-4402"}}],
        }],
    },
    # --- Bluebird concentration: small awards, same buyer ---
    {
        "ocid": "ocds-vn56pm-stub-0009", "id": "rel-0009", "date": "2026-02-02T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2025/2026",
        "buyer": {"name": "Machakos Level 5 Hospital"},
        "tender": {
            "title": "Provision of Cleaning Services",
            "tenderPeriod": {"startDate": "2026-01-05", "endDate": "2026-01-25"},
            "procurementMethod": "open",
            "items": [{"description": "Cleaning services, facility-wide"}],
        },
        "awards": [{
            "id": "awd-0009", "date": "2026-02-02",
            "value": {"amount": 180000, "currency": "KES"},
            "suppliers": [{"name": "Bluebird Supplies Ltd",
                           "identifier": {"scheme": "KE-PPRA", "id": "KE-3391"}}],
        }],
    },
    {
        "ocid": "ocds-vn56pm-stub-0010", "id": "rel-0010", "date": "2026-07-30T00:00:00Z",
        "tag": ["award"], "fiscal_year": "2026/2027",
        "buyer": {"name": "Machakos Level 5 Hospital"},
        "tender": {
            "title": "Supply of Office Consumables",
            "tenderPeriod": {"startDate": "2026-07-01", "endDate": "2026-07-20"},
            "procurementMethod": "open",
            "items": [{"description": "Office consumables, assorted"}],
        },
        "awards": [{
            "id": "awd-0010", "date": "2026-07-30",
            "value": {"amount": 95000, "currency": "KES"},
            "suppliers": [{"name": "Bluebird Supplies Ltd",
                           "identifier": {"scheme": "KE-PPRA", "id": "KE-3391"}}],
        }],
    },
]
