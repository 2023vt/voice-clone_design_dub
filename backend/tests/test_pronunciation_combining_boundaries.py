"""A pronunciation entry must not match part of a Unicode word/grapheme."""

import importlib

import pytest


@pytest.fixture
def pronunciation():
    return importlib.import_module("services.pronunciation")


def test_unaccented_term_does_not_replace_part_of_decomposed_accent(pronunciation):
    text = 'cafe\u0301 cafe'
    assert pronunciation.apply_lexicon(text, {'cafe': 'coffee'}) == 'cafe\u0301 coffee'


def test_indic_term_ending_in_vowel_mark_remains_whole_word(pronunciation):
    term = '\u0915\u093f'  # ki
    longer = '\u0915\u093f\u0938\u093e\u0928'  # kisan
    assert pronunciation.apply_lexicon(f'{longer} {term}', {term: 'ki'}) == f'{longer} ki'


def test_decomposed_whole_word_can_still_be_replaced(pronunciation):
    term = 'cafe\u0301'
    assert pronunciation.apply_lexicon(f'{term}s {term},', {term: 'coffee'}) == f'{term}s coffee,'


def test_letter_after_combining_mark_is_not_a_new_word(pronunciation):
    assert pronunciation.apply_lexicon('a\u0301b b', {'b': 'bee'}) == 'a\u0301b bee'


def test_nonspacing_script_keys_keep_existing_substring_semantics(pronunciation):
    assert pronunciation.apply_lexicon('\u6211\u5728\u5317\u4eac', {'\u5317\u4eac': 'Beijing'}) == '\u6211\u5728Beijing'
