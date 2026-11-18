import json
import duckdb
import pandas as pd
import streamlit as st

DB_PATH = "kdrama_reddit.duckdb"

@st.cache_resource
def get_db_connection():
    return duckdb.connect(DB_PATH, read_only=True)

st.set_page_config(page_title="KDRAMA Reddit Search Engine", layout="wide")

st.title("🎬 KDRAMA Reddit Search Engine")
st.write("Search threads across titles, submission content, or individual comment threads.")

# 1. Search Bar Input
search_phrase = st.text_input(
    "Enter search keyword or phrase:",
    value="Crash Landing on You",
    placeholder="e.g. Twenty-Five Twenty-One, Hospital Playlist, Kim Soo-hyun, etc."
)

# 2. Search Mode Radio Buttons
search_mode = st.radio(
    "Select Search Scope & Ranking:",
    options=[
        "Search Thread Title (Ranked by Total Thread Score)",
        "Search Submission Title + Text (Ranked by Total Thread Score)",
        "Search Any Comment in Thread (Ranked by Term Mentions)"
    ],
    index=0
)

if st.button("🔍 Search Database", type="primary") or search_phrase.strip():
    if not search_phrase.strip():
        st.warning("Please enter a search term.")
        st.stop()

    con = get_db_connection()
    search_term = f"%{search_phrase.strip()}%"
    
    # Setup Progress Bar UI
    progress_bar = st.progress(0, text="Initializing query execution...")
    
    # -------------------------------------------------------------------------
    # MODE 1: Search Thread Title Only
    # -------------------------------------------------------------------------
    if search_mode == "Search Thread Title (Ranked by Total Thread Score)":
        progress_bar.progress(30, text="Searching thread titles...")
        
        query = """
            SELECT 
                thread_identifier,
                thread_title,
                subreddit,
                submission_author,
                comment_count,
                submission_score,
                total_thread_score,
                is_missing_submission,
                to_timestamp(start_timestamp::BIGINT)::VARCHAR AS start_time,
                to_timestamp(end_timestamp::BIGINT)::VARCHAR AS end_time
            FROM threads
            WHERE LOWER(thread_title) LIKE LOWER(?)
            ORDER BY total_thread_score DESC
        """
        results_df = con.execute(query, [search_term]).fetchdf()
        progress_bar.progress(100, text="Done!")

    # -------------------------------------------------------------------------
    # MODE 2: Search Submission Title + Body Text (selftext)
    # -------------------------------------------------------------------------
    elif search_mode == "Search Submission Title + Text (Ranked by Total Thread Score)":
        progress_bar.progress(20, text="Scanning submissions and thread titles...")
        
        query = """
            SELECT DISTINCT
                t.thread_identifier,
                t.thread_title,
                t.subreddit,
                t.submission_author,
                t.comment_count,
                t.submission_score,
                t.total_thread_score,
                t.is_missing_submission,
                to_timestamp(t.start_timestamp::BIGINT)::VARCHAR AS start_time,
                to_timestamp(t.end_timestamp::BIGINT)::VARCHAR AS end_time
            FROM threads t
            LEFT JOIN submissions s ON t.post_id = s.post_id
            WHERE LOWER(t.thread_title) LIKE LOWER(?)
               OR LOWER(COALESCE(s.selftext, '')) LIKE LOWER(?)
            ORDER BY t.total_thread_score DESC
        """
        results_df = con.execute(query, [search_term, search_term]).fetchdf()
        progress_bar.progress(100, text="Done!")

    # -------------------------------------------------------------------------
    # MODE 3: Search Any Comment in Thread (Ranked by Total Term Mentions)
    # -------------------------------------------------------------------------
    else:
        progress_bar.progress(15, text="Aggregating comment matches across threads (this may take a moment)...")
        
        query = """
            WITH comment_matches AS (
                SELECT 
                    CASE 
                        WHEN post_id LIKE 't3_%' THEN SUBSTR(post_id, 4) 
                        ELSE post_id 
                    END AS clean_post_id,
                    -- Count occurrences of term in comment body
                    (LEN(comment_body) - LEN(REPLACE(LOWER(comment_body), LOWER(?), ''))) / LEN(?) AS match_count
                FROM comments
                WHERE LOWER(comment_body) LIKE LOWER(?)
            ),
            thread_mention_counts AS (
                SELECT 
                    clean_post_id,
                    SUM(match_count) AS total_term_mentions
                FROM comment_matches
                GROUP BY clean_post_id
            )
            SELECT 
                t.thread_identifier,
                t.thread_title,
                tmc.total_term_mentions,
                t.subreddit,
                t.submission_author,
                t.comment_count,
                t.submission_score,
                t.total_thread_score,
                t.is_missing_submission,
                to_timestamp(t.start_timestamp::BIGINT)::VARCHAR AS start_time,
                to_timestamp(t.end_timestamp::BIGINT)::VARCHAR AS end_time
            FROM thread_mention_counts tmc
            JOIN threads t ON tmc.clean_post_id = t.post_id
            ORDER BY tmc.total_term_mentions DESC, t.total_thread_score DESC
        """
        raw_term = search_phrase.strip()
        results_df = con.execute(query, [raw_term, raw_term, search_term]).fetchdf()
        progress_bar.progress(100, text="Done!")

    progress_bar.empty() # Remove progress bar on completion
    
    total_found = len(results_df)
    
    if total_found > 0:
        st.success(f"Found **{total_found:,}** matching thread(s).")
        
        # Download Button for ALL results as JSONL
        jsonl_data = results_df.to_json(orient="records", lines=True)
        file_slug = "".join([c if c.isalnum() else "_" for c in search_phrase.strip().lower()])
        download_filename = f"threads_{file_slug}.jsonl"
        
        st.download_button(
            label=f"📥 Download All {total_found:,} Matching Threads (.jsonl)",
            data=jsonl_data,
            file_name=download_filename,
            mime="application/x-ndjson"
        )
        
        st.divider()
        st.subheader("Top 50 Matching Threads")
        st.caption("Click any column header to re-sort results.")
        
        top_50_df = results_df.head(50)
        
        # Configure column display based on mode
        column_config = {
            "thread_identifier": "Thread ID",
            "thread_title": "Title",
            "subreddit": "Subreddit",
            "submission_author": "Author Code",
            "comment_count": st.column_config.NumberColumn("Comments", format="%d"),
            "submission_score": st.column_config.NumberColumn("Post Score", format="%d"),
            "total_thread_score": st.column_config.NumberColumn("Total Score", format="%d"),
            "is_missing_submission": "Missing Post?",
            "start_time": "Start Date",
            "end_time": "Last Comment Date"
        }
        
        if "total_term_mentions" in top_50_df.columns:
            column_config["total_term_mentions"] = st.column_config.NumberColumn(
                "Keyword Mentions", format="%d"
            )

        st.dataframe(
            top_50_df,
            use_container_width=True,
            hide_index=True,
            column_config=column_config
        )
    else:
        st.warning(f"No matching threads found for '{search_phrase}'.")