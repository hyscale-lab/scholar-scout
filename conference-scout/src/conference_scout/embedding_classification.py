import logging
import requests
from scipy.spatial.distance import cosine
from config import AppConfig

logger = logging.getLogger(__name__)

class GeminiEmbeddingSetup:
    # --- MODIFIED PART: Replaced single threshold with dynamic thresholds ---
    ABSTRACT_THRESHOLD = 0.67  # Use when we have a full 300-word abstract
    TITLE_THRESHOLD = 0.60     # Use when Semantic Scholar fails and we only have a title
    
    SINGLE_CLASSIFICATION = False
    DEBUG = True

    # --- RESTORED PART: Re-enabling the Noise/Garbage filter anchors for vector distance checking ---
    NOISE = "NONSENSE GARBAGE NEGATIVE"
    CS = "COMPUTER SCIENCE RELATED RESEARCH PAPER"
    
    SYSTEM_NULLS = ["null value placeholder", "NIL empty string", "undefined variable return", "None type object", "void N/A entry"]
    CONVERSATIONAL = ["hello how can I help", "thanks for the update", "please let me know", "regards and best wishes", "okay cool sounds good"]
    GIBBERISH = ["safasefseaawv", "reagregreea", "fbwafvbskj", "fwefhewilheWLSA"]
    UI_JUNK = ["click here to subscribe", "navigation menu toggle", "footer copyright reserved", "login sign up button", "contact us for support"]
    DOC_META = ["page number citations", "references bibliography list", "table of contents index", "author date published", "figure caption table"]

    FILTER_NONSENSE_TAXONOMY = {
        NOISE: [*SYSTEM_NULLS, *CONVERSATIONAL, *GIBBERISH, *UI_JUNK, *DOC_META],
        CS: [
            "coherent and relevant research paper",
            "computer science research",
            "computer engineering research",
            "Computer science research and engineering principles.",
            "Software systems architecture and implementation.",
            "Algorithmic complexity and data structures.",
            "Distributed systems and network protocols.",
            "Computational performance and hardware optimization.",
        ]
    }

    def __init__(self, config: AppConfig, gemini_client=None):
        self.TAXONOMY = {research_topic.name: research_topic.taxonomy for research_topic in config.research_topics}
        
        # --- MODIFIED PART: Hitting LM Studio's native embedding endpoint ---
        self.OLLAMA_URL = "http://100.105.99.33:11434/v1/embeddings"
        # Using the exact strict model name Dmitrii requested
        self.OLLAMA_MODEL = "text-embedding-nomic-embed-text-v1.5"
        self.precomputed = False

    # --- MODIFIED PART: Added manual batching and verbose server error logging ---
    def get_embedding(self, text_or_list):
        if isinstance(text_or_list, list):
            batch_results = []
            for text in text_or_list:
                try:
                    response = requests.post(self.OLLAMA_URL, json={
                        "model": self.OLLAMA_MODEL,
                        "input": text
                    }, timeout=30)
                    
                    if response.status_code != 200:
                        logger.error(f"LM Studio Error: {response.text}")
                        
                    response.raise_for_status()
                    data = response.json().get("data", [])
                    if data:
                        batch_results.append(data[0]["embedding"])
                except Exception as e:
                    logger.error(f"Failed to fetch batch embedding from LM Studio: {e}")
                    raise
            return batch_results

        try:
            response = requests.post(self.OLLAMA_URL, json={
                "model": self.OLLAMA_MODEL,
                "input": text_or_list
            }, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"LM Studio Error: {response.text}")
                
            response.raise_for_status()
            
            data = response.json().get("data", [])
            if not data:
                logger.error("No embedding data returned from LM Studio.")
                raise ValueError("Empty embeddings response.")
            
            return data[0]["embedding"]
            
        except Exception as e:
            logger.error(f"Failed to fetch single embedding from LM Studio: {e}")
            raise

    # --- RESTORED PART: The Vector Math Calculation Methods ---
    def precompute_category_embeddings(self):
        if self.precomputed:
            return
        
        # Pre-compute Category Centroids using LM Studio
        self.CATEGORY_EMBEDDINGS = {label: self.get_embedding(keywords) for label, keywords in self.TAXONOMY.items()}
        self.NEGATIVE_CS_EMBEDDINGS = {label: self.get_embedding(keywords) for label, keywords in self.FILTER_NONSENSE_TAXONOMY.items()}
        self.precomputed = True

    def text_embedding_classification_result(self, text_vector, category_embeddings):
        category_classification_result = {}
        for category, category_keywords_embeddings in category_embeddings.items():
            # Calculate Cosine Similarity (1 - spatial distance)
            scores = [1 - cosine(text_vector, keyword_vector) for keyword_vector in category_keywords_embeddings]
            category_classification_result[category] = max(scores) if scores else 0.0
        return category_classification_result

    def is_garbage(self, text):
        text = text.strip()
        if len(text) < 5:
            return True
        alpha_chars = sum(c.isalpha() for c in text)
        if alpha_chars / len(text) < 0.5:
            return True
        return False

    def pre_classification_filter(self, text):
        # 1. Base length/density check
        if self.is_garbage(text):
            return None
        
        # 2. Vectorize the abstract
        input_vec = self.get_embedding(text)
        
        # 3. Compare distance to the "NOISE" anchors vs "CS" anchors
        noise_cs_similarities = self.text_embedding_classification_result(input_vec, self.NEGATIVE_CS_EMBEDDINGS)
        
        if noise_cs_similarities[self.NOISE] > noise_cs_similarities[self.CS]:
            return None # Paper is irrelevant
            
        return input_vec 

    # --- RESTORED PART: Reverting back to the geometric categorization bounds ---
    def gemini_embedding_classify(self, paper_abstract):
        if not paper_abstract:
            return []
            
        self.precompute_category_embeddings()
        
        try:
            paper_vector = self.pre_classification_filter(paper_abstract)
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return []
            
        if not paper_vector:
            return [] # Dropped by the NOISE filter
            
        # Calculate similarity against all configured topics
        category_classification_result = self.text_embedding_classification_result(paper_vector, self.CATEGORY_EMBEDDINGS)
        
        if GeminiEmbeddingSetup.DEBUG:
            for category, cat_score in category_classification_result.items():
                logger.info(f"CALIBRATION -> Paper vs {category} @ {cat_score:.4f}")
        
        # --- THE DYNAMIC DBLP FALLBACK THRESHOLD ---
        # If the string is long (> 30 words), it has an abstract. Use our high threshold.
        # If it's short (Title only fallback), drop the threshold to catch it.
        word_count = len(paper_abstract.split())
        applied_threshold = self.ABSTRACT_THRESHOLD if word_count > 30 else self.TITLE_THRESHOLD
        
        if self.SINGLE_CLASSIFICATION:
            best_label = max(category_classification_result, key=category_classification_result.get)
            best_labels = [best_label] if category_classification_result[best_label] >= applied_threshold else []
        else:
            best_labels = [cat for cat, cat_score in category_classification_result.items() if cat_score >= applied_threshold]
        
        return best_labels