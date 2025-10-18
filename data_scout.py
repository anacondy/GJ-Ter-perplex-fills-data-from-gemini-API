import sqlite3
import google.generativeai as genai
import os
import json
import time
import difflib

API_KEY = "KEY HERE"
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(
    'gemini-2.5-pro',
    generation_config={"response_mime_type": "application/json"}
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'jobs.db')

def find_best_match(exam_name_db, results):
    names_in_api = [item.get('exam_name', '') for item in results]
    match = difflib.get_close_matches(exam_name_db, names_in_api, n=1, cutoff=0.4)
    if match:
        for item in results:
            if item.get('exam_name', '') == match[0]:
                return item
    # Also try substring both directions for fallback
    for item in results:
        if exam_name_db.lower() in item.get('exam_name', '').lower() or \
           item.get('exam_name', '').lower() in exam_name_db.lower():
            return item
    return None

def ask_gemini_batch(exam_names):
    prompt = f"""
For each of these government exams in India, provide all details in a single JSON array.

Each item should include:
- exam_name (Echo exactly as input, don't vary)
- nationality
- age_limits
- age_relax
- edu_qual
- attempts
- physical_std
- stages
- num_papers
- q_type
- duration
- marking_scheme
- official_website
- cutoffs (array of {{category, score}})
- year

Exams: {', '.join(exam_names)}

Example format:
[{{"exam_name":"UPSC CSE", "nationality":"...", ... }}, ...]

If information is unavailable for any field, write "Information not available".
Return ONLY valid JSON, no markdown or extra text.
"""
    try:
        response = model.generate_content(prompt)
        print(f"\n📋 Raw API Response (first 500 chars):\n{response.text[:500]}\n")
        data = json.loads(response.text)
        if not isinstance(data, list):
            print(f"❌ ERROR: Expected list, got {type(data)}")
            return []
        return data
    except Exception as e:
        print(f"❌ Gemini/API error: {e}")
        return []

def update_all_job_info():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, exam_name FROM jobs")
    jobs_to_check = cursor.fetchall()
    print("🚀 Starting the Data Scout with batch processing...\n")
    BATCH_SIZE = 5
    for i in range(0, len(jobs_to_check), BATCH_SIZE):
        batch = jobs_to_check[i:i+BATCH_SIZE]
        exam_names = [exam_name for job_id, exam_name in batch]
        print(f"\n📦 Processing batch {i//BATCH_SIZE + 1}: {', '.join(exam_names)}")
        batch_results = ask_gemini_batch(exam_names)
        if not batch_results:
            print("❌ No valid data received for this batch. Skipping...")
            time.sleep(30)
            continue
        for job_id, exam_name in batch:
            exam_data = find_best_match(exam_name, batch_results)
            if not exam_data:
                print(f"⚠️  No data found for {exam_name}")
                continue
            try:
                cursor.execute("DELETE FROM job_specs WHERE job_id = ?", (job_id,))
                cursor.execute(
                    "INSERT INTO job_specs VALUES (NULL,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        exam_data.get('nationality', 'Information not available'),
                        exam_data.get('age_limits', 'Information not available'),
                        exam_data.get('age_relax', 'Information not available'),
                        exam_data.get('edu_qual', 'Information not available'),
                        exam_data.get('attempts', 'Information not available'),
                        exam_data.get('physical_std', 'Information not available')
                    )
                )
                cursor.execute("DELETE FROM exam_pattern WHERE job_id = ?", (job_id,))
                cursor.execute(
                    "INSERT INTO exam_pattern VALUES (NULL,?,?,?,?,?,?)",
                    (
                        job_id,
                        exam_data.get('stages', 'Information not available'),
                        exam_data.get('num_papers', 'Information not available'),
                        exam_data.get('q_type', 'Information not available'),
                        exam_data.get('duration', 'Information not available'),
                        exam_data.get('marking_scheme', 'Information not available')
                    )
                )
                cutoffs = exam_data.get('cutoffs', [])
                cursor.execute("DELETE FROM job_cutoffs WHERE job_id = ?", (job_id,))
                for cutoff in cutoffs:
                    cursor.execute(
                        "INSERT INTO job_cutoffs VALUES (NULL,?,?,?,?)",
                        (
                            job_id,
                            cutoff.get('category', 'Information not available'),
                            cutoff.get('score', 'Information not available'),
                            exam_data.get('year', 'Information not available')
                        )
                    )
                website = exam_data.get('official_website', 'Information not available')
                cursor.execute("UPDATE jobs SET official_website = ? WHERE id = ?", (website, job_id))
                print(f"   ✅ All data updated for {exam_name}")
            except Exception as e:
                print(f"   ❌ Database Error for {exam_name}: {e}")
        conn.commit()
        if i + BATCH_SIZE < len(jobs_to_check):
            print("\n⏳ Waiting 30 seconds before next batch to respect rate limits...")
            time.sleep(30)
    conn.close()
    print("\n🎉 Mission Complete! Database fully updated with real data. ✅")

if __name__ == '__main__':
    update_all_job_info()
