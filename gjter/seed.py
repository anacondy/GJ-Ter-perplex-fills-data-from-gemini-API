"""The base job rows.

These twelve posts are the spine of the database; the enrichment pass fills the
detail tables around them.

The original seed carried invented figures - ``'₹56,100+'`` with a trailing plus,
``'21-32'`` with no reckoning date, and a pay level of 10 asserted for posts
where it is wrong (SBI PO and IBPS PO are bank-scale posts and have no 7th CPC
pay level at all; LIC AAO likewise). Those have been replaced with figures
checked against the conducting bodies, and any field that could not be verified
is ``None`` so the enrichment pass can fill it rather than a guess persisting.

``pay_level`` is only set where a 7th Central Pay Commission level genuinely
applies. ``salary`` records the entry **basic pay**, which is a defined figure,
rather than a vague "in-hand" number that varies by city and DA cycle.
"""

from __future__ import annotations

#: Column order matches :data:`gjter.db.JOBS_COLUMNS`.
SEED_JOBS: tuple[dict, ...] = (
    {
        "post_name": "IAS Officer",
        "exam_name": "UPSC CSE",
        "conducting_body": "UPSC",
        "group": "A",
        "gazetted_status": "Gazetted",
        "pay_level": 10,
        "salary": "₹56,100 basic pay (7th CPC Level 10, Junior Time Scale)",
        "eligibility": "Bachelor's degree in any discipline",
        "age_limit": "21-32 years (unreserved), as on 1 August of the exam year",
        "pet_status": "No PET; medical standards apply on selection",
        "official_website": "https://upsc.gov.in",
        "source_url": "https://upsc.gov.in/examinations/Civil%20Services%20(Preliminary)%20Examination",
        "application_fee": "₹100 (Prelims). SC/ST/PwBD and all female candidates exempt. Mains: ₹200.",
        "vacancies": "979 (CSE 2025, all services combined)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "IPS Officer",
        "exam_name": "UPSC CSE",
        "conducting_body": "UPSC",
        "group": "A",
        "gazetted_status": "Gazetted",
        "pay_level": 10,
        "salary": "₹56,100 basic pay (7th CPC Level 10, Junior Time Scale)",
        "eligibility": "Bachelor's degree in any discipline",
        "age_limit": "21-32 years (unreserved), as on 1 August of the exam year",
        "pet_status": "Physical standards and medical fitness required",
        "official_website": "https://upsc.gov.in",
        "source_url": "https://upsc.gov.in/examinations/Civil%20Services%20(Preliminary)%20Examination",
        "application_fee": "₹100 (Prelims). SC/ST/PwBD and all female candidates exempt. Mains: ₹200.",
        "vacancies": "979 (CSE 2025, all services combined)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "IFS Officer (Indian Foreign Service)",
        "exam_name": "UPSC CSE",
        "conducting_body": "UPSC",
        "group": "A",
        "gazetted_status": "Gazetted",
        "pay_level": 10,
        "salary": "₹56,100 basic pay (7th CPC Level 10, Junior Time Scale)",
        "eligibility": "Bachelor's degree in any discipline",
        "age_limit": "21-32 years (unreserved), as on 1 August of the exam year",
        "pet_status": "No PET; medical standards apply on selection",
        "official_website": "https://upsc.gov.in",
        "source_url": "https://upsc.gov.in/examinations/Civil%20Services%20(Preliminary)%20Examination",
        "application_fee": "₹100 (Prelims). SC/ST/PwBD and all female candidates exempt. Mains: ₹200.",
        "vacancies": "979 (CSE 2025, all services combined)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "RBI Grade B Officer (DR - General)",
        "exam_name": "RBI Grade B Exam",
        "conducting_body": "RBI",
        "group": "A",
        # RBI is not on the central pay matrix; it runs its own officer scale.
        "gazetted_status": "Not applicable (RBI is a statutory body, not a ministry)",
        "pay_level": None,
        "salary": "₹55,200 basic pay in the scale ₹55200-2850(9)-80850-EB-2850(2)-86550-3300(4)-99750",
        "eligibility": "Graduation with 60% marks, or post-graduation with 55%",
        "age_limit": "21-30 years (32 with M.Phil, 34 with Ph.D.)",
        "pet_status": "No PET",
        "official_website": "https://www.rbi.org.in",
        "source_url": "https://opportunities.rbi.org.in",
        "application_fee": "₹850 + 18% GST (General/OBC/EWS); ₹100 + GST (SC/ST/PwBD)",
        "vacancies": "120 (2025: General 83, DEPR 17, DSIM 20)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "SBI Probationary Officer",
        "exam_name": "SBI PO Exam",
        "conducting_body": "SBI",
        "group": "Junior Management Grade Scale I",
        "gazetted_status": "Not applicable (public sector bank officer cadre)",
        "pay_level": None,
        "salary": "₹48,480 basic pay at the first stage of the JMGS-I scale (11th/12th Bipartite Settlement)",
        "eligibility": "Graduation in any discipline",
        "age_limit": "21-30 years, as on the date in the advertisement",
        "pet_status": "No PET",
        "official_website": "https://sbi.co.in/web/careers",
        "source_url": "https://sbi.co.in/web/careers/current-openings",
        "application_fee": "₹750 (General/EWS/OBC); nil for SC/ST/PwBD",
        "vacancies": "541 (2025-26: 500 regular + 41 backlog)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "IBPS Probationary Officer / Management Trainee",
        "exam_name": "IBPS PO Exam",
        "conducting_body": "IBPS",
        "group": "Junior Management Grade Scale I",
        "gazetted_status": "Not applicable (public sector bank officer cadre)",
        "pay_level": None,
        "salary": "₹48,480 basic pay in the scale ₹48480-85920 (JMGS-I)",
        "eligibility": "Graduation in any discipline",
        "age_limit": "20-30 years, as on the date in the notification",
        "pet_status": "No PET",
        "official_website": "https://www.ibps.in",
        "source_url": "https://www.ibps.in/index.php/crp-po-mt/",
        "application_fee": "₹850 (General/OBC/EWS); ₹175 (SC/ST/PwBD)",
        "vacancies": None,
        "vacancies_year": None,
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "Assistant Audit Officer (SSC CGL)",
        "exam_name": "SSC CGL",
        "conducting_body": "SSC",
        "group": "B",
        # AAO is the one CGL post that is Group B *Gazetted* - the original
        # seed marked it Non-Gazetted, which is wrong.
        "gazetted_status": "Gazetted",
        "pay_level": 8,
        "salary": "₹47,600 basic pay (7th CPC Level 8, ₹47,600-1,51,100)",
        "eligibility": "Bachelor's degree; CA/CS/CMA or M.Com desirable",
        "age_limit": "18-30 years, as on the date in the notification",
        "pet_status": "No PET for this post",
        "official_website": "https://ssc.gov.in",
        "source_url": "https://ssc.gov.in/candidate-portal/notice-board",
        "application_fee": "₹100; nil for women, SC, ST, PwBD and eligible ex-servicemen",
        "vacancies": None,
        "vacancies_year": None,
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "NDA Cadet (Army/Navy/Air Force)",
        "exam_name": "NDA Exam",
        "conducting_body": "UPSC",
        "group": "A",
        "gazetted_status": "Commissioned officer on completion of training",
        "pay_level": 10,
        "salary": "₹56,100 basic pay on commissioning as Lieutenant (Level 10); "
                  "stipend of ₹56,100 in the final year of training",
        "eligibility": "10+2; Physics, Chemistry and Maths for Air Force and Naval wings",
        "age_limit": "Approx. 16.5-19.5 years; exact date-of-birth window per notification",
        "pet_status": "Physical and medical standards required; SSB includes group tests",
        "official_website": "https://upsc.gov.in",
        "source_url": "https://upsc.gov.in/examinations/National%20Defence%20Academy%20and%20Naval%20Academy%20Examination",
        "application_fee": "₹100; nil for SC/ST, female candidates and wards of JCOs/NCOs/ORs",
        "vacancies": "406 (NDA & NA II 2025)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "ISRO Scientist/Engineer 'SC'",
        "exam_name": "ISRO ICRB",
        "conducting_body": "ISRO",
        "group": "A",
        "gazetted_status": "Gazetted",
        "pay_level": 10,
        "salary": "₹56,100 basic pay (7th CPC Level 10, ₹56,100-1,77,500)",
        "eligibility": "BE/B.Tech with 65% aggregate or CGPA 6.84/10",
        "age_limit": "Up to 28 years (30 for ME/M.Tech entry)",
        "pet_status": "No PET",
        "official_website": "https://www.isro.gov.in/CareerOpportunities.html",
        "source_url": "https://www.isro.gov.in/CareerOpportunities.html",
        "application_fee": "₹750 initially; refunded in full to SC/ST/PwBD/women/ex-servicemen and ₹500 refunded to others on appearing (net ₹250)",
        "vacancies": "320 (ICRB 2025, Advt. ISRO:ICRB:02(EMC):2025)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "DRDO Scientist 'B'",
        "exam_name": "DRDO Entry Test",
        "conducting_body": "DRDO",
        "group": "A",
        "gazetted_status": "Gazetted",
        "pay_level": 10,
        "salary": "₹56,100 basic pay (7th CPC Level 10)",
        "eligibility": "First-class BE/B.Tech or M.Sc in the relevant discipline, with a valid GATE score",
        "age_limit": "Up to 35 years (unreserved) under the GATE-based advertisement",
        "pet_status": "No PET",
        "official_website": "https://rac.gov.in",
        "source_url": "https://rac.gov.in",
        "application_fee": "₹100 (General/OBC/EWS); nil for SC/ST/PwBD and all female candidates",
        "vacancies": "152 (2025, Advt. No. 156)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "Indian Engineering Service Officer (Railways)",
        "exam_name": "UPSC ESE",
        "conducting_body": "UPSC",
        "group": "A",
        "gazetted_status": "Gazetted",
        "pay_level": 10,
        "salary": "₹56,100 basic pay (7th CPC Level 10, Junior Time Scale)",
        "eligibility": "Degree in engineering, or Sections A and B of the Institution of Engineers (India)",
        "age_limit": "21-30 years, as on 1 January of the exam year",
        "pet_status": "Service-specific physical and medical standards apply",
        "official_website": "https://upsc.gov.in",
        "source_url": "https://upsc.gov.in/examinations/Engineering%20Services%20Examination",
        "application_fee": "₹200; nil for SC/ST/PwBD and all female candidates",
        "vacancies": "457 (ESE 2025, including IRMS)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
    {
        "post_name": "LIC Assistant Administrative Officer (Generalist)",
        "exam_name": "LIC AAO Exam",
        "conducting_body": "LIC",
        "group": "Class I Officer",
        "gazetted_status": "Not applicable (LIC is a statutory corporation)",
        "pay_level": None,
        "salary": "₹88,635 basic pay in the scale ₹88635-4385(14)-150025-4750(4)-169025",
        "eligibility": "Bachelor's degree in any discipline",
        "age_limit": "21-30 years, as on the date in the notification",
        "pet_status": "No PET; pre-recruitment medical examination applies",
        "official_website": "https://licindia.in/web/guest/careers",
        "source_url": "https://licindia.in/web/guest/careers",
        "application_fee": "₹700 + GST (General/OBC/EWS); ₹85 + GST (SC/ST/PwBD)",
        "vacancies": "350 (AAO Generalist, 2025; 841 across all AAO/AE posts)",
        "vacancies_year": "2025",
        "verified_on": "2026-07-27",
    },
)


def seed(conn, *, progress=None) -> tuple[int, int]:
    """Insert or update the base rows. Idempotent.

    Returns:
        ``(inserted, updated)`` counts.
    """
    from . import db

    emit = progress or (lambda _msg: None)
    inserted = updated = 0

    with db.transaction(conn):
        for row in SEED_JOBS:
            existing = conn.execute(
                "SELECT id FROM jobs WHERE post_name = ? AND exam_name = ?",
                (row["post_name"], row["exam_name"]),
            ).fetchone()
            db.upsert_job(conn, dict(row))
            if existing is None:
                inserted += 1
            else:
                updated += 1

    emit(f"Seed applied: {inserted} inserted, {updated} updated.")
    return inserted, updated
