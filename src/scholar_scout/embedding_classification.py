import logging

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from scipy.spatial.distance import cosine
from .config import AppConfig

logger = logging.getLogger(__name__)

class GeminiEmbeddingSetup:
    CLASSIFICATION_THRESHOLD = 0.80
    SINGLE_CLASSIFICATION = True
    DEBUG = False

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

    STOPWORDS = {"i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they", "them", "their", "theirs", "themselves", "what", "which", "who", "whom", "this", "that", "these", "those", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "having", "do", "does", "did", "doing", "a", "an", "the", "and", "but", "if", "or", "because", "as", "until", "while", "of", "at", "by", "for", "with", "about", "against", "between", "into", "through", "during", "before", "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off", "over", "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just", "don", "should", "now"}
    WHITELIST = {"AI", "GPU", "SLA", "API", "CPU", "RAM", "LLM", "AWS", "FAAS", "PUE"}


    def __init__(self, config: AppConfig, gemini_client: genai.Client):

        self.client = gemini_client
        
        self.TAXONOMY = {research_topic.name: research_topic.taxonomy for research_topic in config.research_topics}
        self.GEMINI_EMBEDDING_MODEL = config.gemini.embedding_model

        self.precomputed = False
    
    def precompute_category_embeddings(self):
        if self.precomputed:
            return  # Already pre-computed
        
        # Pre-compute Category Centroids
        self.CATEGORY_EMBEDDINGS = {label: self.get_category_embeddings(keywords) for label, keywords in self.TAXONOMY.items()}
        self.NEGATIVE_CS_EMBEDDINGS = {label: self.get_category_embeddings(keywords) for label, keywords in self.FILTER_NONSENSE_TAXONOMY.items()}

        self.precomputed = True


    def get_category_embeddings(self, keywords):
        # Get embeddings for all keywords in the list
        result = self.client.models.embed_content(
            model=self.GEMINI_EMBEDDING_MODEL,
            contents=keywords,
            config=types.EmbedContentConfig(task_type="CLASSIFICATION")
        )
        if not result.embeddings:
            logger.error("Failed to get embeddings for category keywords.")
            raise ValueError("Embeddings result is None or empty.")
        if any(emb.values is None for emb in result.embeddings):
            logger.error("One or more embedding values are None for category keywords.")
            raise ValueError("Embedding values are None.")

        keyword_vectors = [keyword_ContentEmbedding.values for keyword_ContentEmbedding in result.embeddings]
        # Return all keyword vectors for individual similarity comparison
        return keyword_vectors

    def text_embedding_classification_result(self, text_vector, category_embeddings):
        category_classification_result = {}

        # Manual Cosine Similarity
        for category, category_keywords_embeddings in category_embeddings.items():
            scores = [1 - cosine(text_vector, keyword_vector) for keyword_vector in category_keywords_embeddings]
            if scores:
                if GeminiEmbeddingSetup.DEBUG:
                    logger.debug("%s @ %f \n%s !!\n", category, max(scores), scores)
                category_classification_result[category] = max(scores)
            else:
                category_classification_result[category] = 0.0
                logger.error("Error computing cosine similarity for category '%s'. Check if embeddings are valid.", category)
        if GeminiEmbeddingSetup.DEBUG:
            logger.debug("###\n")

        return category_classification_result
        
    def get_embedding(self, text):
        text_result = self.client.models.embed_content(
            model=self.GEMINI_EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(task_type="CLASSIFICATION")
        )
        if not text_result.embeddings or text_result.embeddings[0].values is None:
            logger.error("Failed to get valid embedding for text.")
            raise ValueError("Embeddings result is None or empty.")
        text_vector = text_result.embeddings[0].values
        return text_vector

    def is_garbage(self, text):
        text = text.strip()

        # 1. Length Filter (with Whitelist exception)
        if len(text) < 5 and text.upper() not in GeminiEmbeddingSetup.WHITELIST:
            return True, "Too short"

        # 2. Alphabetical Ratio (Density check)
        # Checks if the string is mostly symbols/numbers
        alpha_chars = sum(c.isalpha() for c in text)
        if alpha_chars / len(text) < 0.5:
            return True, "Low alphabet density"

        # 3. Stopword Check (Is it just filler?)
        words = text.lower().split()
        if all(word in GeminiEmbeddingSetup.STOPWORDS for word in words):
            return True, "Only stopwords"

        return False, "Pass"


    def pre_classification_filter(self, text):
        if GeminiEmbeddingSetup.DEBUG:
            logger.debug(f"ABSTRACT FOR FILTERING: {text}")

        # Step 1: Heuristics // without embedding
        garbage, reason = self.is_garbage(text)
        if garbage:
            if GeminiEmbeddingSetup.DEBUG:
                logger.debug(reason)
            return None  # Discard
        
        # Step 2: Vectorize
        input_vec = self.get_embedding(text)
        
        # Step 3: Compare to Anchors
        # (Simplified logic)
        noise_cs_similarities = self.text_embedding_classification_result(input_vec, self.NEGATIVE_CS_EMBEDDINGS)
        sim_to_noise = noise_cs_similarities[GeminiEmbeddingSetup.NOISE]
        sim_to_cs = noise_cs_similarities[GeminiEmbeddingSetup.CS]

        if sim_to_noise > sim_to_cs:
            return None # Noise
        
        return input_vec # to use for classification into the categories


    def gemini_embedding_classify(self, paper_abstract):
        logger.debug(f"DEBUG MODE: {GeminiEmbeddingSetup.DEBUG}")
        logger.debug(f"SINGLE_CLASSIFICATION: {GeminiEmbeddingSetup.SINGLE_CLASSIFICATION}")
        logger.debug(f"CLASSIFICATION_THRESHOLD: {GeminiEmbeddingSetup.CLASSIFICATION_THRESHOLD}")

        self.precompute_category_embeddings()

        labels = list(self.TAXONOMY.keys())
        if len(labels) == 0:
            logger.error("No categories defined in taxonomy.")
            return []
        logger.info("labels: %s", labels)

        if paper_abstract == "":
            logger.info("NO PAPER ABSTRACT")
            return []

        # 1. Embed your Abstract to check if is a paper to classify into categories
        try:
            paper_vector = self.pre_classification_filter(paper_abstract)
        except (ServerError, ClientError) as e:
            logger.error(f"Gemini is currently overloaded or down: {e}")
            return []

        if not paper_vector:
            logger.info("NOT CS RELATED, NO NEED FOR CLASSIFICATION")
            return []

        logger.info("abstract: %s", paper_abstract[:50])

        # 2. Manual Cosine Similarity
        category_classification_result = self.text_embedding_classification_result(paper_vector, self.CATEGORY_EMBEDDINGS)

        if GeminiEmbeddingSetup.SINGLE_CLASSIFICATION:
            best_label = max(category_classification_result, key=category_classification_result.get)
            best_labels = [best_label] if category_classification_result[best_label] >= self.CLASSIFICATION_THRESHOLD else []
        else:
            # other approach using threshold
            # >1 can be classified into
            best_labels = [cat for cat, cat_score in category_classification_result.items() if cat_score >= GeminiEmbeddingSetup.CLASSIFICATION_THRESHOLD]
            logger.info(f"best_labels: {best_labels}")

        logger.info(f"Final best labels: {best_labels}")
        return best_labels