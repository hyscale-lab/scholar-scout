import os
import json
import logging
import requests
import sys
import re

# Ensure script can import from src and src/conference_scout directly
# This prevents the "ModuleNotFoundError: No module named 'config'" error
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(project_root_path, "src", "conference_scout"))
sys.path.insert(0, os.path.join(project_root_path, "src"))

from embedding_classification import GeminiEmbeddingSetup
from config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SERVER_URL = "http://100.105.99.33:11434"
GEN_MODEL = "qwen/qwen3.6-35b-a3b"

def ask_qwen_judge(title: str, abstract: str) -> dict:
    """Uses the generative model to establish a high-confidence Multi-Label Silver Ground Truth."""
    prompt = f"""Task: Classify this computer science paper into the relevant categories from this list:
[LLM Inference, Serverless Computing, VLM Inference, Sustainable Computing]
A paper can belong to multiple categories (1 to 3 max). If it fits none of these, use ["Others"].

Paper Title: {title}
Abstract: {abstract}

Output EXACTLY in this JSON format, nothing else:
{{"Categories": ["name1", "name2"], "Confidence": 95, "Reason": "short sentence explaining why"}}"""

    try:
        response = requests.post(f"{SERVER_URL}/v1/chat/completions", json={
            "model": GEN_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0
        # Increased timeout to 180 seconds because 35B parameter models take time to process
        }, timeout=180) 
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        
        # Extract JSON safely
        match = re.search(r'\{.*?\}', content.replace('\n', ''), re.DOTALL)
        return json.loads(match.group()) if match else None
    except Exception as e:
        logger.error(f"Qwen judging failed for '{title[:30]}': {e}")
        return None

def run_benchmark():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config = load_config(os.path.join(project_root, "config", "config.yml"))
    
    with open(os.path.join(project_root, "data", "papers_enriched.json"), "r") as f:
        all_papers = json.load(f)
    
    # Run on a robust sample size
    sample_papers = all_papers
    #[:60]
    silver_dataset = []
    
    logger.info("="*60)
    logger.info(f"PHASE 1: Generating Multi-Label Silver Labels via {GEN_MODEL}")
    logger.info("="*60)
    
    for p in sample_papers:
        title = p.get("title", "")
        abstract = p.get("abstract", "")
        
        judge_result = ask_qwen_judge(title, abstract)
        if judge_result and judge_result.get("Confidence", 0) >= 90:
            silver_dataset.append({
                "text": f"{title} {abstract}",
                "true_labels": judge_result.get("Categories", ["Others"]),
                "confidence": judge_result.get("Confidence"),
                "reason": judge_result.get("Reason")
            })
            logger.info(f"  [+] Kept: '{title[:30]}...' -> {judge_result.get('Categories')} (Conf: {judge_result.get('Confidence')}%)")
        elif judge_result:
            logger.info(f"  [-] Dropped (Low Conf): '{title[:30]}...' (Conf: {judge_result.get('Confidence')}%)")

    logger.info("\n" + "="*60)
    logger.info("PHASE 2: Extracting Raw Cosine Scores via Nomic Embeddings")
    logger.info("="*60)
    
    classifier = GeminiEmbeddingSetup(config)
    classifier.precompute_category_embeddings()
    
    all_raw_scores = []
    
    # Pre-calculate raw scores for all high-confidence papers
    for item in silver_dataset:
        vec = classifier.get_embedding(item["text"])
        item["raw_scores"] = classifier.text_embedding_classification_result(vec, classifier.CATEGORY_EMBEDDINGS)
        all_raw_scores.extend(item["raw_scores"].values())

    if all_raw_scores:
        logger.info(f"Empirical Score Range for this dataset: Min = {min(all_raw_scores):.3f}, Max = {max(all_raw_scores):.3f}")

    logger.info("\n" + "="*60)
    logger.info("PHASE 3: Sweeping Thresholds for Maximum Multi-Label F1 Score")
    logger.info("="*60)
    
    # Sweep from 0.40 to 0.85 to capture wider variances based on the empirical range
    thresholds = [x / 100.0 for x in range(40, 86, 1)] 
    best_threshold = 0
    max_f1 = -1
    best_precision = 0
    best_recall = 0

    for t in thresholds:
        tp, fp, fn = 0, 0, 0
        
        for item in silver_dataset:
            true_set = set(item["true_labels"])
            raw_scores = item["raw_scores"]
            
            # Predict labels based on current threshold candidate
            predicted = [cat for cat, score in raw_scores.items() if score >= t]
            pred_set = set(predicted)
            
            # Strict Multi-Label Math Evaluation with proper "Others" handling
            if "Others" in true_set:
                if not pred_set:
                    tp += 1  # Both agreed the paper belongs in 'Others' (no target categories)
                else:
                    fp += len(pred_set)  # Nomic hallucinated categories for an 'Others' paper
            else:
                if not pred_set:
                    fn += len(true_set)  # Nomic missed all true categories
                else:
                    tp += len(true_set & pred_set)
                    fp += len(pred_set - true_set)
                    fn += len(true_set - pred_set)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        if f1 > max_f1:
            max_f1 = f1
            best_threshold = t
            best_precision = precision
            best_recall = recall
            
    logger.info(f"\n[RESULTS] Optimal Mathematical Threshold: {best_threshold:.2f}")
    logger.info(f"[RESULTS] Peak Multi-Label F1 Score: {max_f1:.3f} (Precision: {best_precision:.3f}, Recall: {best_recall:.3f})")

if __name__ == "__main__":
    run_benchmark()