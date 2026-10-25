import unittest
from Backend.Commands import parse_command, parse_commands

class BrowserSearchCommandTests(unittest.TestCase):
    def test_spoken_pause_after_google_keeps_provider_and_query(self):
        for phrase in ('Search Google. Who is Elon Musk.', 'Search on Google for Who is Elon Musk', 'Google search: Who is Elon Musk'):
            command=parse_command(phrase)
            self.assertEqual((command.action,command.target,command.options),('web','Who is Elon Musk',{'engine':'google'}))

    def test_provider_only_request_opens_site(self):
        for engine in ('youtube','google'):
            command=parse_command('Search on '+engine)
            self.assertEqual((command.action,command.target),('open',engine))

    def test_adjacent_search_keeps_requested_site(self):
        commands=parse_commands('Search on YouTube and search play video on Ray.')
        self.assertEqual(len(commands),2)
        self.assertEqual(commands[0].target,'youtube')
        self.assertEqual(commands[1].options,{'engine':'youtube'})
        self.assertEqual(commands[1].target,'play video on Ray')

    def test_explicit_provider_overrides_previous_one(self):
        commands=parse_commands('open youtube and search google for universities')
        self.assertEqual(commands[-1].options,{'engine':'google'})

    def test_provider_does_not_leak_past_other_actions_or_requests(self):
        commands=parse_commands('open youtube and open notepad and search for universities')
        self.assertEqual(commands[-1].options,{})
        self.assertEqual(parse_command('search for universities').options,{})

    def test_dictation_and_query_punctuation_remain_literal(self):
        text='Search Google. Who is Elon Musk and search on YouTube!'
        commands=parse_commands('type '+text)
        self.assertEqual(len(commands),1)
        self.assertEqual(commands[0].target,text)
        self.assertEqual(parse_command('search google for example.com API v2.1').target,'example.com API v2.1')

    def test_question_forms_are_treated_as_requests(self):
        # "are you able to open X" must act like "open X", not fall to chat denial.
        for phrase in ('are you able to open youtube', 'do you know how to open youtube',
                       'is it possible to open youtube', 'can you open youtube',
                       'could you open youtube', 'will you open youtube'):
            command = parse_command(phrase)
            self.assertEqual((command.action, command.target), ('open', 'youtube'), phrase)

    def test_question_forms_reach_other_actions_too(self):
        self.assertEqual(parse_command('are you able to play relaxing music'),
                         parse_command('play relaxing music'))
        self.assertEqual(parse_command('do you know how to search google for ai news'),
                         parse_command('search google for ai news'))
        self.assertEqual(parse_command('can you open notepad').target, 'notepad')
