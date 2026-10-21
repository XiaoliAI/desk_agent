import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.rag.embeddings import EmbeddingService


class RemoteEmbeddingTests(unittest.TestCase):
    @patch("core.rag.embeddings._embedding_config", return_value=({}, {}))
    def test_batches_and_restores_response_order(self, _config):
        client = Mock()
        client.embeddings.create.side_effect = [
            SimpleNamespace(data=[
                SimpleNamespace(index=1, embedding=[0, 2]),
                SimpleNamespace(index=0, embedding=[3, 0]),
            ]),
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0, 4])]),
        ]
        service = EmbeddingService(api_key="test-key", batch_size=2, client=client)

        self.assertEqual(
            service.embed_documents(["first", "second", "third"]),
            [[1.0, 0.0], [0.0, 1.0], [0.0, 1.0]],
        )
        self.assertEqual(client.embeddings.create.call_count, 2)
        self.assertEqual(client.embeddings.create.call_args_list[0].kwargs["input"], ["first", "second"])

    @patch("core.rag.embeddings._embedding_config", return_value=({}, {}))
    def test_rejects_missing_vectors(self, _config):
        client = Mock()
        client.embeddings.create.return_value = SimpleNamespace(data=[])
        service = EmbeddingService(api_key="test-key", client=client)
        with self.assertRaisesRegex(ValueError, "count"):
            service.embed_query("question")

    @patch("core.rag.embeddings._embedding_config", return_value=({}, {}))
    def test_accepts_dashscope_repeated_zero_indices(self, _config):
        client = Mock()
        client.embeddings.create.return_value = SimpleNamespace(data=[
            SimpleNamespace(index=0, embedding=[2, 0]),
            SimpleNamespace(index=0, embedding=[0, 3]),
        ])
        service = EmbeddingService(api_key="test-key", client=client)

        self.assertEqual(
            service.embed_documents(["first", "second"]),
            [[1.0, 0.0], [0.0, 1.0]],
        )

    @patch("core.rag.embeddings._embedding_config", return_value=({}, {}))
    def test_embedding_error_is_actionable_and_redacts_credentials(self, _config):
        client = Mock()
        client.embeddings.create.side_effect = RuntimeError(
            "request failed api_key=sk-ws-12345678901234567890"
        )
        service = EmbeddingService(api_key="test-key", client=client)

        with self.assertRaises(RuntimeError) as raised:
            service.embed_query("question")

        message = str(raised.exception)
        self.assertIn("type=RuntimeError", message)
        self.assertIn("api_key=[REDACTED]", message)
        self.assertNotIn("sk-ws-12345678901234567890", message)


if __name__ == "__main__":
    unittest.main()
