import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from app.agent import answer
from app.main import app


class InventoryTests(unittest.TestCase):
    def test_floor_count_and_followup(self):
        first = answer('how many units of SKU-4821 are in aisle seven?')
        self.assertEqual(first['totals'], {'on_hand': 204, 'available': 168, 'reserved': 24, 'held': 12})
        followup = answer('where is it in all aisles?', first['context'])
        self.assertEqual(len(followup['bins']), 3)
        self.assertEqual(followup['totals']['available'], 328)
        self.assertEqual(answer('repeat', followup['context'])['reply'], followup['reply'])

    def test_spoken_digits(self):
        self.assertEqual(answer('SKU four eight two one aisle seven')['status'], 'found')

    def test_ambiguity_preserves_aisle(self):
        first = answer('where is the stretch wrap in aisle 7?')
        self.assertEqual(first['status'], 'clarify')
        second = answer('18 inch', first['context'])
        self.assertEqual(second['totals']['on_hand'], 204)
        self.assertEqual(answer('12 inch', answer('where is the wrap?')['context'])['status'], 'found')

    def test_fail_closed(self):
        for text, status in [('SKU 4829', 'not_found'), ('SKU 4821 aisle 99', 'no_location'), ('reserve SKU 4821', 'unsupported'), ('cancel', 'reset'), ('hello', 'clarify')]:
            self.assertEqual(answer(text)['status'], status)
        self.assertNotIn('totals', answer('compare SKU 4821 and SKU 4822'))
        self.assertEqual(answer('gloves')['totals']['available'], 0)
        self.assertIn('No units', answer('labels')['reply'])
        self.assertEqual(answer('where is it', {'sku': ['bad'], 'aisle': 'bad'})['status'], 'clarify')


class APITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_text_without_key(self):
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': ''}):
            data = self.client.post('/api/query', json={'text': 'SKU 4821 aisle 7'}).json()
        self.assertEqual(data['totals']['available'], 168)
        self.assertIsNone(data['audio'])
        self.assertIn('not configured', data['voice_error'])
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.post('/api/query', json={'text': ''}).status_code, 422)

    def test_elevenlabs_contract(self):
        requests = []
        async def post(client, url, **kwargs):
            requests.append((url, kwargs))
            if 'speech-to-text' in url:
                return httpx.Response(200, json={'text': 'SKU 4821 aisle 7'})
            return httpx.Response(200, content=b'mp3-test-bytes', headers={'content-type': 'audio/mpeg'})
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test-key'}, clear=True), patch.object(httpx.AsyncClient, 'post', post):
            transcript = self.client.post('/api/transcribe', files={'file': ('query.webm', b'clip', 'audio/webm')})
            data = self.client.post('/api/query', json={'text': transcript.json()['text']}).json()
        self.assertTrue(data['audio'])
        self.assertEqual(requests[0][1]['data']['model_id'], 'scribe_v2')
        self.assertIn('S K U 4 8 2 1', requests[1][1]['json']['text'])
        self.assertEqual(requests[1][1]['headers']['xi-api-key'], 'test-key')

    def test_provider_failure_keeps_lookup(self):
        async def post(*args, **kwargs):
            return httpx.Response(429)
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test-key'}, clear=True), patch.object(httpx.AsyncClient, 'post', post):
            data = self.client.post('/api/query', json={'text': 'gloves'}).json()
            failed = self.client.post('/api/transcribe', files={'file': ('query.webm', b'clip', 'audio/webm')})
        self.assertEqual(data['status'], 'found')
        self.assertIn('quota', data['voice_error'])
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(self.client.post('/api/transcribe', files={'file': ('bad', b'clip', 'text/plain')}).status_code, 415)


if __name__ == '__main__':
    unittest.main()
