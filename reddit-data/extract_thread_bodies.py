import os
import csv
import json
import duckdb
import pandas as pd

def extract_thread_ids(file_path):
    """Extracts thread IDs from a JSONL file."""
    thread_ids = []
    
    if file_path.endswith(".jsonl"):
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    t_id = data.get("thread_identifier") or data.get("post_id") or data.get("thread_id")
                    if t_id:
                        thread_ids.append(t_id)                   
    return thread_ids

def export_threads_to_jsonl(input_file, db_path, output_dir="exported_threads"):
    """Given a file with thread id-s, searches for them in the given DB an stores
    the content of the threads into a folder, in separate files.
    """
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found.")
        return
        
    os.makedirs(output_dir, exist_ok=True)
    con = duckdb.connect(db_path, read_only=True)
    
    threads_to_export = extract_thread_ids(input_file)
    print(f"Found {len(threads_to_export):,} threads in '{input_file}'. Starting export to '{output_dir}/'...")
    
    exported_count = 0
    
    for thread_id in threads_to_export:
        clean_post_id = thread_id[3:] if str(thread_id).startswith("t3_") else str(thread_id)
        
        # 1. Fetch Submission record
        sub_result = con.execute("SELECT * FROM submissions WHERE post_id = ?", [clean_post_id]).fetchdf()
        
        # 2. Fetch Comment records
        comment_query = """
            SELECT * FROM comments 
            WHERE (CASE WHEN post_id LIKE 't3_%' THEN SUBSTR(post_id, 4) ELSE post_id END) = ?
            ORDER BY created_utc ASC
        """
        comments_result = con.execute(comment_query, [clean_post_id]).fetchdf()
        
        if sub_result.empty and comments_result.empty:
            continue
            
        safe_filename = "".join([c if c.isalnum() or c in ("-", "_") else "_" for c in str(thread_id)])
        out_file_path = os.path.join(output_dir, f"{safe_filename}.jsonl")
        
        # 3. Write full thread details to individual JSONL
        with open(out_file_path, "w", encoding="utf-8") as out_file:
            if not sub_result.empty:
                sub_dict = sub_result.iloc[0].to_dict()
                sub_dict = {k: (None if pd.isna(v) else v) for k, v in sub_dict.items()}
                out_file.write(json.dumps(sub_dict) + "\n")
                
            if not comments_result.empty:
                for _, comment_row in comments_result.iterrows():
                    comment_dict = comment_row.to_dict()
                    comment_dict = {k: (None if pd.isna(v) else v) for k, v in comment_dict.items()}
                    out_file.write(json.dumps(comment_dict) + "\n")
                    
        exported_count += 1
        
    con.close()
    print(f"Done! Exported {exported_count:,} full thread file(s) to '{output_dir}/'.")

if __name__ == "__main__":

    INPUT_FILE = "threads_my_dearest.jsonl" 
    DATABASE_FILE = "kdrama_reddit.duckdb"
    OUTPUT_FOLDER = "exported_threads"
    
    export_threads_to_jsonl(INPUT_FILE, DATABASE_FILE, OUTPUT_FOLDER)