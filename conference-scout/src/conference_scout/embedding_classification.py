import logging
import requests  # <-- ADDED PART: Used to hit Dmitrii's local Ollama API
from config import AppConfig

# --- REMOVED PART: Google GenAI and SciPy Math libraries are no longer needed ---
# from google import genai
# from google.genai import types
# from google.genai.errors import ClientError, ServerError
# from scipy.spatial.distance import cosine

logger = logging.getLogger(__name__)

class GeminiEmbeddingSetup:
    # Keeping the class variables and constants identical so the rest of the core pipeline doesn't break
    CLASSIFICATION_THRESHOLD = 0.80
    SINGLE_CLASSIFICATION = False
    DEBUG = False

    # --- REMOVED PART: These massive static text arrays and noise anchors were completely 
    #     deprecated because the Qwen LLM handles text filtering natively via prompt instructions. ---
    # NOISE = "NONSENSE GARBAGE NEGATIVE"
    # CS = "COMPUTER SCIENCE RELATED RESEARCH PAPER"
    # SYSTEM_NULLS = ["null value placeholder", "NIL empty string", "undefined variable return", "None type object", "void N/A entry"]
    # CONVERSATIONAL = ["hello how can I help", "thanks for the update", "please let me know", "regards and best wishes", "okay cool sounds good"]
    # GIBBERISH = ["safasefseaawv", "reagregreea", "fbwafvbskj", "fwefhewilheWLSA"]
    # UI_JUNK = ["click here to subscribe", "navigation menu toggle", "footer copyright reserved", "login sign up button", "contact us for support"]
    # DOC_META = ["page number citations", "references bibliography list", "table of contents index", "author date published", "figure caption table"]
    # FILTER_NONSENSE_TAXONOMY = {
    #     NOISE: [*SYSTEM_NULLS, *CONVERSATIONAL, *GIBBERISH, *UI_JUNK, *DOC_META],
    #     CS: [
    #         "coherent and relevant research paper",
    #         "computer science research",
    #         "computer engineering research",
    #         "Computer science research and engineering principles.",
    #         "Software systems architecture and implementation.",
    #         "Algorithmic complexity and data structures.",
    #         "Distributed systems and network protocols.",
    #         "Computational performance and hardware optimization.",
    #     ]
    # }
    # STOPWORDS = {"i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they", "them", "their", "theirs", "themselves", "what", "which", "who", "whom", "this", "that", "these", "those", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "having", "do", "does", "did", "doing", "a", "an", "the", "and", "but", "if", "or", "because", "as", "until", "while", "of", "at", "by", "for", "with", "about", "against", "between", "into", "through", "during", "before", "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off", "over", "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just", "don", "should", "now"}
    # WHITELIST = {"AI", "GPU", "SLA", "API", "CPU", "RAM", "LLM", "AWS", "FAAS", "PUE"}

    def __init__(self, config: AppConfig, gemini_client=None):
        # --- MODIFIED PART: Swapped out the old initialization tracking variables ---
        # self.client = gemini_client
        # self.GEMINI_EMBEDDING_MODEL = config.gemini.embedding_model
        # self.precomputed = False

        self.TAXONOMY = {research_topic.name: research_topic.taxonomy for research_topic in config.research_topics}
        
        # --- ADDED PART: API routing configuration for Dmitrii's local hosting cluster ---
        self.OLLAMA_URL = "http://100.105.99.33:11434/v1/chat/completions"
        self.OLLAMA_MODEL = self._get_model_name()

    # --- ADDED PART: Automated utility to safely extract model status from the server ---
    def _get_model_name(self):
        try:
            resp = requests.get("http://100.105.99.33:11434/v1/models", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                if models:
                    return models[0]["id"]
        except Exception as e:
            logger.error(f"Failed to fetch model name: {e}")
        return "qwen"

    # --- REMOVED PART: The vector math calculation methods are obsolete on text-generation nodes ---
    # def precompute_category_embeddings(self):
    #     if self.precomputed:
    #         return
    #     self.CATEGORY_EMBEDDINGS = {label: self.get_category_embeddings(keywords) for label, keywords in self.TAXONOMY.items()}
    #     self.NEGATIVE_CS_EMBEDDINGS = {label: self.get_category_embeddings(keywords) for label, keywords in self.FILTER_NONSENSE_TAXONOMY.items()}
    #     self.precomputed = True

    # def get_category_embeddings(self, keywords):
    #     result = self.client.models.embed_content(
    #         model=self.GEMINI_EMBEDDING_MODEL,
    #         contents=keywords,
    #         config=types.EmbedContentConfig(task_type="CLASSIFICATION")
    #     )
    #     return [keyword_ContentEmbedding.values for keyword_ContentEmbedding in result.embeddings]

    # def text_embedding_classification_result(self, text_vector, category_embeddings):
    #     category_classification_result = {}
    #     for category, category_keywords_embeddings in category_embeddings.items():
    #         scores = [1 - cosine(text_vector, keyword_vector) for keyword_vector in category_keywords_embeddings]
    #         category_classification_result[category] = max(scores) if scores else 0.0
    #     return category_classification_result
        
    # def get_embedding(self, text):
    #     text_result = self.client.models.embed_content(
    #         model=self.GEMINI_EMBEDDING_MODEL,
    #         contents=text,
    #         config=types.EmbedContentConfig(task_type="CLASSIFICATION")
    #     )
    #     return text_result.embeddings[0].values

    # --- MODIFIED PART: Stripped down the heavy stopword/whitelist rules to run an O(1) basic string length density check ---
    def is_garbage(self, text):
        text = text.strip()
        if len(text) < 5:
            return True
        alpha_chars = sum(c.isalpha() for c in text)
        if alpha_chars / len(text) < 0.5:
            return True
        return False

        # --- REMOVED HEURISTIC SUB-CHECKS ---
        # if len(text) < 5 and text.upper() not in GeminiEmbeddingSetup.WHITELIST:
        #     return True, "Too short"
        # words = text.lower().split()
        # if all(word in GeminiEmbeddingSetup.STOPWORDS for word in words):
        #     return True, "Only stopwords"

    # --- REMOVED PART: The middleman embedding filter step was entirely discarded ---
    # def pre_classification_filter(self, text):
    #     garbage, reason = self.is_garbage(text)
    #     if garbage: return None
    #     input_vec = self.get_embedding(text)
    #     noise_cs_similarities = self.text_embedding_classification_result(input_vec, self.NEGATIVE_CS_EMBEDDINGS)
    #     if noise_cs_similarities[GeminiEmbeddingSetup.NOISE] > noise_cs_similarities[GeminiEmbeddingSetup.CS]:
    #         return None
    #     return input_vec

    # --- MODIFIED PART: Complete redesign from Vector Angle Proximity to Direct Prompt Engineering ---
    def gemini_embedding_classify(self, paper_abstract):
        if not paper_abstract or self.is_garbage(paper_abstract):
            return []
            
        labels = list(self.TAXONOMY.keys())
        if not labels:
            return []

        # --- ADDED PART: Constructing context strings directly out of config targets ---
        cat_descriptions = "\n".join([f"- {cat}" for cat in labels])
        
        prompt = f"""You are an expert academic research classifier.
Read the following research paper title/abstract and classify it into ONE OR MORE of these exact categories if it matches. 

CATEGORIES:
{cat_descriptions}

ABSTRACT:
{paper_abstract}

If it matches any categories, reply ONLY with a comma-separated list of the exact category names.
If it does not fit any categories, or is not a computer science paper, reply with EXACTLY the word: NONE.
Do not include any explanations, greetings, or extra text."""

        try:
            # --- ADDED PART: Direct HTTP text generation payload execution ---
            response = requests.post(self.OLLAMA_URL, json={
                "model": self.OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 50
            }, timeout=30)
            response.raise_for_status()
            
            result_text = response.json()["choices"][0]["message"]["content"].strip()
            logger.info(f"Qwen classified as: {result_text}")
            
            if "NONE" in result_text.upper():
                return []
                
            # Map the text response back to your config's taxonomy keys
            best_labels = [label for label in labels if label.lower() in result_text.lower()]
            return best_labels

        except Exception as e:
            logger.error(f"Classification via Qwen chat failed: {e}")
            return []

        # --- REMOVED PART: Old baseline code tracking geometric score bounds ---
        # self.precompute_category_embeddings()
        # try:
        #     paper_vector = self.pre_classification_filter(paper_abstract)
        # except (ServerError, ClientError) as e:
        #     return []
        # if not paper_vector: return []
        # category_classification_result = self.text_embedding_classification_result(paper_vector, self.CATEGORY_EMBEDDINGS)
        # if GeminiEmbeddingSetup.SINGLE_CLASSIFICATION:
        #     best_label = max(category_classification_result, key=category_classification_result.get)
        #     best_labels = [best_label] if category_classification_result[best_label] >= self.CLASSIFICATION_THRESHOLD else []
        # else:
        #     best_labels = [cat for cat, cat_score in category_classification_result.items() if cat_score >= GeminiEmbeddingSetup.CLASSIFICATION_THRESHOLD]
        # return best_labels