import unittest

from app import app, fix_mojibake_text


class TextEncodingGuardTests(unittest.TestCase):
    def test_fix_mojibake_text_common_cases(self):
        self.assertEqual(fix_mojibake_text("NÃ£o foi possÃ­vel"), "Não foi possível")
        self.assertEqual(fix_mojibake_text("ReuniÃ£o"), "Reunião")
        self.assertEqual(fix_mojibake_text("PrÃ³xima aÃ§Ã£o"), "Próxima ação")

    def test_agenda_page_has_no_mojibake_markers(self):
        app.testing = True
        with app.test_client() as client:
            response = client.get("/login")
            text = response.get_data(as_text=True)
            for bad in ("Ã£", "Ã§", "Ã¡", "Ã©", "Ã­", "Ã³", "Ãº", "Â·"):
                self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
