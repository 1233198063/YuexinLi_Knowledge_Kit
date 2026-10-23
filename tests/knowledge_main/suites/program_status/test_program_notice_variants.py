"""Additional source-language invariants for the second implementation iteration."""
import unittest
from test_program_status import answer, OPEN_Q


class NoticeVariants(unittest.TestCase):
    def test_now_before_status_and_literal_negative_status(self):
        for body, expected in [('Applications are now closed.', 'closed'),
                               ('Applications are not currently open.', 'not open'),
                               ('Applications are not yet open.', 'not yet open')]:
            a = answer(body)
            self.assertTrue(a.confident, a.text)
            self.assertIn(expected, a.text.lower())

    def test_when_are_open_requests_the_complete_window(self):
        body = 'Applications are open from March 8, 2034 through May 17, 2034.'
        a = answer(body, 'When are nonprofit grant applications open?')
        self.assertTrue(a.confident)
        self.assertIn('March 8, 2034', a.text)
        self.assertIn('May 17, 2034', a.text)
        self.assertNotIn('window is open', a.text.lower())

    def test_both_requested_bounds_cannot_be_confident_if_one_is_missing(self):
        a = answer('Application period begins March 8, 2034.',
                   'When does the nonprofit grant application period begin and end?')
        self.assertFalse(a.confident)
        self.assertIn("don't know", a.text.lower())


if __name__ == '__main__':
    unittest.main()
