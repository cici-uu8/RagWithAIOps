import unittest
from unittest.mock import Mock, patch

from app.services.vector_search_service import VectorSearchService


class VectorSearchServiceTests(unittest.TestCase):
    def test_search_connects_milvus_before_getting_collection(self):
        service = VectorSearchService()
        collection = Mock()
        collection.search.return_value = [[]]

        with (
            patch(
                "app.services.vector_search_service.vector_embedding_service.embed_query",
                return_value=[0.1] * 1024,
            ),
            patch("app.services.vector_search_service.milvus_manager") as manager,
        ):
            manager.get_collection.return_value = collection

            results = service.search_similar_documents("现场设备故障", top_k=2)

        manager.connect.assert_called_once_with()
        manager.get_collection.assert_called_once_with()
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
