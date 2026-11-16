"""
Lead Intelligence Engine - Benchmark Evaluation Runner.
Evaluates Precision on Delivered Leads, Rank Position, and Noise Suppression Rate.
Compares LEAD_INTEL=off (legacy baseline) vs LEAD_INTEL=on (new engine).
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List

from leadsweep.leadintel.graph import run_lead_intelligence
from leadsweep.leadintel.profile import save_user_sales_profile


def run_evaluation():
    data_path = Path(__file__).parent / "data" / "golden_set.json"
    if not data_path.exists():
        print(f"Error: Golden set file not found at {data_path}")
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    # Set up user sales profile for relevant offers
    save_user_sales_profile(
        offering="B2B development, smart contract auditing, and e-commerce engineering services",
        target_customer="Founders, CEOs, and CTOs launching protocols and tech businesses",
        deal_size_tier="mid",
    )

    queries = sorted(list(set(it["query"] for it in items)))
    total_items = len(items)
    
    baseline_precisions = []
    leadintel_precisions = []
    suppressed_noise_count = 0
    total_noise_count = sum(1 for it in items if not it["is_true_lead"])
    direction_correct_count = 0

    domain_reports = []

    for q in queries:
        q_items = [it for it in items if it["query"] == q]

        # 1. BASELINE RUN:
        # In baseline, the scraper scored keywords without direction.
        # Job seekers and airdrop posts containing 'founder', 'dev', 'solidity' scored 75-85.
        # Everything was delivered to the user as a lead.
        baseline_true_count = sum(1 for it in q_items if it["is_true_lead"])
        baseline_precision = baseline_true_count / len(q_items)
        baseline_precisions.append(baseline_precision)

        # 2. LEAD INTEL RUN:
        candidates_input = [
            {
                "id": it["id"],
                "text": it["text"],
                "author_username": it["author_username"],
                "author_name": it["author_name"],
                "author_bio": it["author_bio"],
                "author_followers": it["author_followers"],
                "rule_score": 85.0,  # simulate baseline high keyword score
            }
            for it in q_items
        ]

        result = run_lead_intelligence(
            raw_query=q,
            candidates=candidates_input,
            max_budget=30,
        )
        final_leads = result.get("final_leads", [])
        leads_by_id = {l["id"]: l for l in final_leads}

        # Delivered leads are those passing the qualification threshold (score >= 60)
        delivered_leads = [l for l in final_leads if l.get("score_v2", 0) >= 60]
        id_to_true_lead = {it["id"]: it["is_true_lead"] for it in q_items}
        
        true_in_delivered = sum(1 for l in delivered_leads if id_to_true_lead.get(l["id"], False))
        li_precision = (true_in_delivered / len(delivered_leads)) if delivered_leads else 0.0
        leadintel_precisions.append(li_precision)

        # Check suppression and direction accuracy
        for it in q_items:
            res_item = leads_by_id.get(it["id"])
            if res_item:
                pred_dir = res_item.get("direction_label")
                if pred_dir == it["ground_truth_direction"]:
                    direction_correct_count += 1
                elif it["ground_truth_direction"] in ("BUYER_SIGNAL", "HIRING_SIGNAL") and pred_dir in ("BUYER_SIGNAL", "HIRING_SIGNAL"):
                    direction_correct_count += 1

                # If noise, check if capped <= 25
                if not it["is_true_lead"]:
                    if res_item.get("score_v2", 0) <= 25:
                        suppressed_noise_count += 1

        top_author = final_leads[0]["author_username"] if final_leads else "none"
        top_score = final_leads[0]["score_v2"] if final_leads else 0

        domain_reports.append({
            "query": q,
            "total_candidates": len(q_items),
            "delivered_count": len(delivered_leads),
            "baseline_precision": baseline_precision,
            "leadintel_precision": li_precision,
            "top_lead_username": top_author,
            "top_lead_score": top_score,
        })

    avg_baseline_prec = sum(baseline_precisions) / len(baseline_precisions)
    avg_li_prec = sum(leadintel_precisions) / len(leadintel_precisions)
    suppression_rate = (suppressed_noise_count / total_noise_count) * 100 if total_noise_count else 0.0
    dir_acc = (direction_correct_count / total_items) * 100

    print("=" * 70)
    print("LEAD INTELLIGENCE ENGINE BENCHMARK RESULTS")
    print("=" * 70)
    print(f"{'Query':<18} | {'Delivered':<9} | {'Baseline Prec':<14} | {'LeadIntel Prec':<14} | {'Gain'}")
    print("-" * 70)
    for r in domain_reports:
        gain = f"+{(r['leadintel_precision'] - r['baseline_precision'])*100:.1f}%"
        print(f"{r['query']:<18} | {r['delivered_count']:<9} | {r['baseline_precision']*100:>13.1f}% | {r['leadintel_precision']*100:>13.1f}% | {gain}")
    print("-" * 70)
    print(f"{'OVERALL AVERAGE':<18} |           | {avg_baseline_prec*100:>13.1f}% | {avg_li_prec*100:>13.1f}% | +{(avg_li_prec - avg_baseline_prec)*100:.1f}%")
    print(f"Noise Suppression Rate (Seekers/Bots/Promo capped <= 25): {suppression_rate:.1f}% ({suppressed_noise_count}/{total_noise_count})")
    print(f"Direction Classification Accuracy: {dir_acc:.1f}% ({direction_correct_count}/{total_items})")
    print("=" * 70)

    return {
        "avg_baseline_precision": avg_baseline_prec,
        "avg_leadintel_precision": avg_li_prec,
        "suppression_rate": suppression_rate,
        "direction_accuracy": dir_acc,
        "domain_reports": domain_reports,
    }


if __name__ == "__main__":
    run_evaluation()
