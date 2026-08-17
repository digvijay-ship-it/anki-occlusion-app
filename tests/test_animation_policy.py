import os
import unittest
from unittest.mock import patch

from ui.canvas import retro_effects


class AnimationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.first_mode = object()
        self.second_mode = object()
        retro_effects.resume_animations(self.first_mode)
        retro_effects.resume_animations(self.second_mode)

    def tearDown(self):
        retro_effects.resume_animations(self.first_mode)
        retro_effects.resume_animations(self.second_mode)

    def test_work_modes_pause_effects_until_the_last_mode_closes(self):
        with patch.dict(os.environ, {"ANKI_HOME_ANIMATIONS": "1"}, clear=False):
            self.assertTrue(retro_effects._home_animations_enabled())

            retro_effects.suspend_animations(self.first_mode)
            retro_effects.suspend_animations(self.second_mode)
            self.assertTrue(retro_effects.animations_suspended())
            self.assertFalse(retro_effects._home_animations_enabled())

            retro_effects.resume_animations(self.first_mode)
            self.assertFalse(retro_effects._home_animations_enabled())

            retro_effects.resume_animations(self.second_mode)
            self.assertFalse(retro_effects.animations_suspended())
            self.assertTrue(retro_effects._home_animations_enabled())
