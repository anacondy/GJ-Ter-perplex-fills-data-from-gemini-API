# database_setup.py
# FINAL version with robust job detail structure and matching columns!

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'jobs.db')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# --- Drop all tables to ensure a clean start ---
cursor.execute('DROP TABLE IF EXISTS job_specs')
cursor.execute('DROP TABLE IF EXISTS exam_pattern')
cursor.execute('DROP TABLE IF EXISTS job_cutoffs')
cursor.execute('DROP TABLE IF EXISTS jobs')

# --- Recreate jobs table with all columns for display and AI integration ---
cursor.execute('''
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_name TEXT,
    exam_name TEXT,
    conducting_body TEXT,
    "group" TEXT,
    gazetted_status TEXT,
    pay_level INTEGER,
    salary TEXT,
    eligibility TEXT,
    age_limit TEXT,
    pet_status TEXT,
    application_start TEXT,
    application_end TEXT,
    exam_date TEXT,
    official_website TEXT
);
''')

# --- Related detail tables for AI population ---
cursor.execute('''
CREATE TABLE job_specs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    nationality TEXT,
    age_limits TEXT,
    age_relax TEXT,
    edu_qual TEXT,
    attempts TEXT,
    physical_std TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
''')

cursor.execute('''
CREATE TABLE exam_pattern (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    stages TEXT,
    num_papers TEXT,
    q_type TEXT,
    duration TEXT,
    marking_scheme TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
''')

cursor.execute('''
CREATE TABLE job_cutoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    category TEXT,
    score TEXT,
    year TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
''')

# --- 12 Base Jobs, Gemini will fill missing fields ---
jobs_data = [
    ('IAS Officer', 'UPSC CSE', 'UPSC', 'A', 'Gazetted', 10, '₹56,100+', 'Any Graduation', '21-32', 'No PET', None, None, None, None),
    ('IPS Officer', 'UPSC CSE', 'UPSC', 'A', 'Gazetted', 10, '₹56,100+', 'Any Graduation', '21-32', 'PET Required', None, None, None, None),
    ('IFS Officer', 'UPSC CSE', 'UPSC', 'A', 'Gazetted', 10, '₹60,000+', 'Any Graduation', '21-32', 'No PET', None, None, None, None),
    ('RBI Grade B', 'RBI Grade B Exam', 'RBI', 'A', 'Gazetted', 10, '₹70,000+', 'Graduation (50%+)', '21-30', 'No PET', None, None, None, None),
    ('SBI PO', 'SBI PO Exam', 'SBI', 'A', 'Gazetted', 7, '₹40,000+', 'Any Graduation', '21-30', 'No PET', None, None, None, None),
    ('IBPS PO', 'IBPS PO Exam', 'IBPS', 'A', 'Gazetted', 7, '₹35,000+', 'Any Graduation', '20-30', 'No PET', None, None, None, None),
    ('SSC CGL (AAO)', 'SSC CGL', 'SSC', 'B', 'Non-Gazetted', 8, '₹45,000+', 'Any Graduation', '18-32', 'No PET', None, None, None, None),
    ('NDA Officer', 'NDA Exam', 'UPSC', 'A', 'Gazetted', 10, '₹56,100+', '10+2 (PCM)', '16.5-19.5', 'PET Required', None, None, None, None),
    ('ISRO Scientist', 'ISRO ICRB', 'ISRO', 'A', 'Gazetted', 10, '₹60,000+', 'B.Tech/B.E (60%+)', '21-35', 'No PET', None, None, None, None),
    ('DRDO Scientist', 'DRDO Entry Test', 'DRDO', 'A', 'Gazetted', 10, '₹60,000+', 'B.Tech/B.E (First Class)', '21-28', 'No PET', None, None, None, None),
    ('Railway Group A', 'UPSC ESE', 'UPSC', 'A', 'Gazetted', 10, '₹56,100+', 'B.Tech/B.E', '21-30', 'No PET', None, None, None, None),
    ('LIC AAO', 'LIC AAO Exam', 'LIC', 'B', 'Non-Gazetted', 8, '₹40,000+', 'Any Graduation', '21-30', 'No PET', None, None, None, None)
]
cursor.executemany(
    '''INSERT INTO jobs VALUES 
    (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
    jobs_data
)

conn.commit()
conn.close()
print("✅ Database 'jobs.db' has been successfully built with all necessary columns! 🚀")
