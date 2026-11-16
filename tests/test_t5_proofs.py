import json
import os
import shutil
import tempfile
import pytest
from leadsweep.core.datasets import DatasetEngine
from leadsweep.pipeline.store import Store
from leadsweep.api import _fetch_run_items, get_v1_job, unified_data_export
from leadsweep.config import get_settings

@pytest.mark.asyncio
async def test_t5_timeline_rerun_and_profile_proofs():
    td = tempfile.mkdtemp()
    try:
        db_path = os.path.join(td, "test_t5.db")
        st = Store(db_path)
        st.close()
        engine = DatasetEngine(db_path)
        
        orig_env_db = os.environ.get("LEADSWEEP_DB_PATH")
        os.environ["LEADSWEEP_DB_PATH"] = db_path
        
        try:
            # 1. Timeline run 1 with 3 tweets
            run1_id, ds1_id = engine.create_run(
                actor_name="user_tweets",
                input_data={"handle": "testuser", "platform": "twitter", "max_results": 3},
                user_email="owner@example.com"
            )
            
            for i in range(1, 4):
                item_dict = {
                    "id": f"tweet_{i}",
                    "rest_id": f"tweet_{i}",
                    "author_username": "testuser",
                    "author_name": "Test User",
                    "text": f"Tweet post number {i}",
                    "created_at": f"2026-10-18T10:0{i}:00Z",
                    "like_count": 10 * i,
                    "reply_count": i,
                    "retweet_count": i,
                    "author_followers": 500,
                    "platform": "twitter",
                }
                engine.append_item(ds1_id, f"tweet_{i}", "user_tweets", item_dict, dedup=True)
                
            # Insert into tweets and scores for run 1
            st_active = Store(db_path)
            now = "2026-10-18T10:00:00Z"
            for i in range(1, 4):
                st_active.db.execute(
                    """
                    INSERT OR IGNORE INTO tweets(id, text, author_username, author_name, created_at, first_run_id, platform)
                    VALUES (?, ?, ?, ?, ?, ?, 'twitter')
                    """,
                    (f"tweet_{i}", f"Tweet post number {i}", "testuser", "Test User", f"2026-10-18T10:0{i}:00Z", run1_id)
                )
                st_active.db.execute(
                    """
                    INSERT OR REPLACE INTO scores(tweet_id, run_id, score, category, reason, action, scored_by, scored_at, signals)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"tweet_{i}", run1_id, 85, "lead", "High buyer intent", "Direct Message", "llm", now, json.dumps({"evaluator": "llm", "primary_category": "lead"}))
                )
            st_active.db.commit()
            st_active.close()
            engine.finish_run(run1_id, status="succeeded", items_count=3)
            
            # Verify run 1
            items_run1 = _fetch_run_items(run1_id)
            assert len(items_run1) == 3
            assert items_run1[0]["score"] == 85
            
            # 2. Timeline run 2 for SAME user with the SAME 3 tweets
            run2_id, ds2_id = engine.create_run(
                actor_name="user_tweets",
                input_data={"handle": "testuser", "platform": "twitter", "max_results": 3},
                user_email="owner@example.com"
            )
            for i in range(1, 4):
                item_dict = {
                    "id": f"tweet_{i}",
                    "rest_id": f"tweet_{i}",
                    "author_username": "testuser",
                    "author_name": "Test User",
                    "text": f"Tweet post number {i}",
                    "created_at": f"2026-10-18T10:0{i}:00Z",
                    "like_count": 10 * i,
                    "reply_count": i,
                    "retweet_count": i,
                    "author_followers": 500,
                    "platform": "twitter",
                }
                # Per-run item linking
                engine.append_item(ds2_id, f"tweet_{i}", "user_tweets", item_dict, dedup=True)
            engine.finish_run(run2_id, status="succeeded", items_count=3)
            
            # PROOF CHECKS for second run:
            # second run's items_count == its dataset rows == popup rows == CSV rows == JSON rows
            ds2_items = engine.get_dataset_items(ds2_id)
            popup_rows = _fetch_run_items(run2_id)
            
            csv_resp = unified_data_export(scope="job", job_id=run2_id, format="csv", kind="leads")
            csv_chunks = [chunk async for chunk in csv_resp.body_iterator]
            csv_body = b"".join(csv_chunks)
            csv_lines = [l for l in csv_body.decode("utf-8").strip().splitlines() if l.strip()]
            csv_data_rows = csv_lines[1:]
            
            json_resp = unified_data_export(scope="job", job_id=run2_id, format="json", kind="leads")
            json_data = json.loads(json_resp.body.decode("utf-8"))
            
            assert len(ds2_items) == 3
            assert len(popup_rows) == 3
            assert len(csv_data_rows) == 3
            assert len(json_data) == 3
            assert 3 == len(ds2_items) == len(popup_rows) == len(csv_data_rows) == len(json_data)
            
            # First-run scores intact, no duplicate tweets rows in global tweets table
            st_check = Store(db_path)
            tweets_count = st_check.db.execute("SELECT COUNT(*) FROM tweets WHERE id LIKE 'tweet_%'").fetchone()[0]
            assert tweets_count == 3  # exactly 3, not 6
            scores_count = st_check.db.execute("SELECT COUNT(*) FROM scores WHERE tweet_id LIKE 'tweet_%'").fetchone()[0]
            assert scores_count == 3
            for r in popup_rows:
                assert r["score"] == 85
                assert r["evaluator"] == "llm"
            st_check.close()
            
            # 3. Profile run: renders real fields and is never sent to the judge
            run_p_id, ds_p_id = engine.create_run(
                actor_name="profile",
                input_data={"handle": "nextjs", "platform": "twitter", "max_results": 1, "type": "profile"},
                user_email="owner@example.com"
            )
            profile_dict = {
                "handle": "nextjs",
                "name": "Next.js",
                "bio": "The React Framework – created and maintained by @vercel.",
                "location": "Global",
                "website": "https://nextjs.org",
                "followers": 150000,
                "following": 50,
                "posts_count": 3200,
                "is_blue_verified": True,
                "joined": "April 2016",
                "fetched_at": "2026-10-18T12:00:00Z",
                "platform": "twitter",
            }
            engine.append_item(ds_p_id, "nextjs", "profile", profile_dict, dedup=True)
            engine.finish_run(run_p_id, status="succeeded", items_count=1, error_detail="1 profile record")
            
            p_items = _fetch_run_items(run_p_id)
            assert len(p_items) == 1
            prof = p_items[0]
            assert prof["is_profile"] is True
            assert prof["name"] == "Next.js"
            assert prof["handle"] == "nextjs"
            assert prof["bio"] == "The React Framework – created and maintained by @vercel."
            assert prof["location"] == "Global"
            assert prof["website"] == "https://nextjs.org"
            assert prof["followers"] == 150000
            assert prof["following"] == 50
            assert prof["posts_count"] == 3200
            assert prof["is_blue_verified"] is True
            assert prof["joined"] == "April 2016"
            assert prof["fetched_at"] == "2026-10-18T12:00:00Z"
            # Never sent to judge: evaluator is None, leadScore is None, leadCategory is Profile
            assert prof["evaluator"] is None
            assert prof["leadScore"] is None
            assert prof["leadCategory"] == "Profile"
            
            # 4. Profile CSV has the BOM and header + 1 row
            p_csv_resp = unified_data_export(scope="job", job_id=run_p_id, format="csv", kind="leads")
            p_chunks = [chunk async for chunk in p_csv_resp.body_iterator]
            p_csv_body = b"".join(p_chunks)
            
            # Check BOM (first 3 bytes: \xef\xbb\xbf)
            assert p_csv_body[:3] == b"\xef\xbb\xbf", f"Expected UTF-8 BOM, got {p_csv_body[:3]}"
            p_lines = [l for l in p_csv_body.decode("utf-8").strip().splitlines() if l.strip()]
            assert len(p_lines) == 2, f"Expected header + 1 row, got {len(p_lines)} lines: {p_lines}"
            
            # Verify header columns
            expected_header = '"handle","name","bio","location","website","followers","following","posts","verified","profile url","fetched at"'
            assert p_lines[0] == expected_header or all(c in p_lines[0] for c in ["handle", "name", "bio", "followers", "verified"]), f"Header mismatch: {p_lines[0]}"
            assert "nextjs" in p_lines[1]
            assert "Next.js" in p_lines[1]
            
            print("ALL T5 TEMP-DB PROOFS PASSED!")
            
        finally:
            if orig_env_db is not None:
                os.environ["LEADSWEEP_DB_PATH"] = orig_env_db
            else:
                os.environ.pop("LEADSWEEP_DB_PATH", None)
    finally:
        shutil.rmtree(td, ignore_errors=True)
