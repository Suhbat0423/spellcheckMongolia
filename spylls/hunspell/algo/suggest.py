from typing import Iterator, List, Set, Union

import dataclasses
from dataclasses import dataclass

from spylls.hunspell import data
from spylls.hunspell.algo.capitalization import Type as CapType
from spylls.hunspell.algo import ngram_suggest, phonet_suggest, permutations as pmt

MAXPHONSUGS = 2
MAXSUGGESTIONS = 5
GOOD_EDITS = ['spaceword', 'uppercase', 'replchars']


@dataclass
class Suggestion:
    """
    Suggestions is what Suggest produces internally to store enough information about some suggestion
    to make sure it is a good one.
    """

    
    text: str

    kind: str

    def __repr__(self):
        return f"Suggestion[{self.kind}]({self.text})"

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)


@dataclass
class MultiWordSuggestion:
    """
    Represents suggestion to split words into several.
    """

 
    words: List[str]

    source: str

   
    allow_dash: bool = True

    def stringify(self, separator=' '):
        return Suggestion(separator.join(self.words), self.source)

    def __repr__(self):
        return f"Suggestion[{self.source}]({self.words!r})"


class Suggest:
    """
    ``Suggest`` object is created on :class:`Dictionary <spylls.hunspell.Dictionary>` reading. Typically,
    you would not use it directly, but you might want for experiments::

        >>> dictionary = Dictionary.from_files('dictionaries/en_US')
        >>> suggest = dictionary.suggester

        >>> [*suggest('spylls')]
        ['spells', 'spills']

        >>> for suggestion in suggest.suggestions('spylls'):
        ...    print(suggestion)
        Suggestion[badchar](spell)
        Suggestion[badchar](spill)

    See :meth:`__call__` as the main entry point for algorithm explanation.

    **Main methods**

    .. automethod:: __call__
    .. automethod:: suggestions

    **Suggestion types**

    .. automethod:: edits
    .. automethod:: ngram_suggestions
    .. automethod:: phonet_suggestions
    """
    def __init__(self, aff: data.Aff, dic: data.Dic, lookup):
        self.aff = aff
        self.dic = dic
        self.lookup = lookup

        # TODO: also NONGRAMSUGGEST and ONLYUPCASE
        bad_flags = {*filter(None, [self.aff.FORBIDDENWORD, self.aff.NOSUGGEST, self.aff.ONLYINCOMPOUND])}

        self.words_for_ngram = [word for word in self.dic.words if not bad_flags.intersection(word.flags)]

    def __call__(self, word: str) -> Iterator[str]:
        """
        Outer "public" interface: returns a list of all valid suggestions, as strings.

        Method returns a generator, so it is up to client code to fetch as many suggestions as it
        needs::

            >>> suggestions = suggester('unredable')
            <generator object Suggest.__call__ at 0x7f74f5056350>
            >>> suggestions.__next__()
            'unreadable'

        Note that suggestion to split words in two also returned as a single string, with a space::

            >>> [*suggester('badcat')]
            ['bad cat', 'bad-cat', 'baccarat']

        Internally, the method just calls :meth:`suggestions` (which returns instances of :class:`Suggestion`)
        and yields suggestion texts.

        Args:
            word: Word to check
        """
        yield from (suggestion.text for suggestion in self.suggestions(word))

    def suggestions(self, word: str) -> Iterator[Suggestion]:  
        """
        Main suggestion search loop. What it does, in general, is:

        * generates possible misspelled word cases (for ex., "KIttens" in dictionary might've been
          'KIttens', 'kIttens', 'kittens', or 'Kittens')
        * produces word edits with :meth:`edits` (with the help of
          :mod:`permutations <spylls.hunspell.algo.permutations>` module), checks them with
          :class:`Lookup <spylls.hunspell.algo.lookup.Lookup>`, and decides if that's maybe enough
        * but if it is not (and if .aff settings allow), ngram-based suggestions are produced with
          :meth:`ngram_suggestions`, and phonetically similar suggestions with :meth:`phonet_suggestions`

        That's very simplified explanation, read the code!

        Args:
            word: Word to check
        """

      
        def is_good_suggestion(word):
           
            return any(self.lookup.good_forms(word, capitalization=False, allow_nosuggest=False))

      
        def is_forbidden(word):
            return self.aff.FORBIDDENWORD and self.dic.has_flag(word, self.aff.FORBIDDENWORD)

        
        handled: Set[str] = set()

        
        def handle_found(suggestion, *, check_inclusion=False):
            text = suggestion.text

            
            if (self.aff.KEEPCASE and self.dic.has_flag(text, self.aff.KEEPCASE) and not
                    (self.aff.CHECKSHARPS and 'ß' in text)):
                # Don't try to change text's case
                pass
            else:
               
                text = self.aff.casing.coerce(text, captype)
              
                if text != suggestion.text and is_forbidden(text):
                    text = suggestion.text

              
                if captype in [CapType.HUH, CapType.HUHINIT] and ' ' in text:
                    pos = text.find(' ')
                    if text[pos + 1] != word[pos] and text[pos + 1].upper() == word[pos]:
                        text = text[:pos+1] + word[pos] + text[pos+2:]

            
            if is_forbidden(text):
                return

          
            text = self.aff.OCONV(text) if self.aff.OCONV else text

           
            if text in handled:
                return

          
            if check_inclusion and any(previous.lower() in text.lower() for previous in handled):
                return

         
            handled.add(text)

            
            yield suggestion.replace(text=text)

    
        captype, variants = self.aff.casing.corrections(word)

      
        if self.aff.FORCEUCASE and captype == CapType.NO:
            for capitalized in self.aff.casing.capitalize(word):
                if is_good_suggestion(capitalized):
                    yield from handle_found(Suggestion(capitalized.capitalize(), 'forceucase'))
                    return  

        good_edits_found = False

       
        for idx, variant in enumerate(variants):
        
            if idx > 0 and is_good_suggestion(variant):
                yield from handle_found(Suggestion(variant, 'case'))

           

            nocompound = False

         
            for suggestion in self.edit_suggestions(variant, handle_found, limit=MAXSUGGESTIONS, compounds=False):
                yield suggestion
            
                good_edits_found = good_edits_found or (suggestion.kind in GOOD_EDITS)
            
                if suggestion.kind in ['uppercase', 'replchars', 'mapchars']:
                    nocompound = True
           
                if suggestion.kind == 'spaceword':
                    return

         
            if not nocompound:
                for suggestion in self.edit_suggestions(variant, handle_found,
                                                        limit=self.aff.MAXCPDSUGS, compounds=True):
                    yield suggestion
                    good_edits_found = good_edits_found or (suggestion.kind in GOOD_EDITS)

        if good_edits_found:
            return

       
        if '-' in word and not any('-' in sug for sug in handled):
            chunks = word.split('-')
            for idx, chunk in enumerate(chunks):
              
                if not is_good_suggestion(chunk):
                   
                    for sug in self(chunk):
                        candidate = '-'.join([*chunks[:idx], sug, *chunks[idx+1:]])
                      
                        if self.lookup(candidate):
                            yield Suggestion(candidate, 'dashes')
                
                    break

      
        ngrams_seen = 0
        for sug in self.ngram_suggestions(word, handled=handled):
            for res in handle_found(Suggestion(sug, 'ngram'), check_inclusion=True):
                ngrams_seen += 1
                yield res
            if ngrams_seen >= self.aff.MAXNGRAMSUGS:
                break

       

        phonet_seen = 0
        for sug in self.phonet_suggestions(word):
            for res in handle_found(Suggestion(sug, 'phonet'), check_inclusion=True):
                phonet_seen += 1
                yield res
            if phonet_seen >= MAXPHONSUGS:
                break

    def edit_suggestions(self, word: str, handle_found, *, compounds: bool, limit: int) -> Iterator[Suggestion]:
        def is_good_suggestion(word):
         
            if compounds:
                return any(self.lookup.good_forms(word, capitalization=False, allow_nosuggest=False, affix_forms=False))
            return any(self.lookup.good_forms(word, capitalization=False, allow_nosuggest=False, compound_forms=False))

    
        def filter_suggestions(suggestions):
            for suggestion in suggestions:
            
                if isinstance(suggestion, MultiWordSuggestion):
             
                    if all(is_good_suggestion(word) for word in suggestion.words):
                     
                        yield suggestion.stringify()
                        if suggestion.allow_dash:
                      
                            yield suggestion.stringify('-')
                else:
               
                    if is_good_suggestion(suggestion.text):
                        yield suggestion

        count = 0

        for suggestion in filter_suggestions(self.edits(word)):
          
            for res in handle_found(suggestion):
                yield res
                count += 1

                if count > limit:
                    return

    def edits(self, word: str) -> Iterator[Union[Suggestion, MultiWordSuggestion]]:
        """
        Produces all possible word edits in a form of :class:`Suggestion` or :class:`MultiWordSuggestion`.
        Note that:

        * order is important, that's the order user will receive the suggestions (and the further the
          suggestion type in the order, the more probably it would be dropped due to suggestion count
          limit)
        * suggestion "source" tag is important: :meth:`suggestions` uses it to distinguish between
          good and questionble edits (if there were any good ones, ngram suggestion wouldn't
          be used)

        Args:
            word: Word to mutate
        """
        
        yield Suggestion(self.aff.casing.upper(word), 'uppercase')

      
        for suggestion in pmt.replchars(word, self.aff.REP):
            if isinstance(suggestion, list):
                yield Suggestion(' '.join(suggestion), 'replchars')
                yield MultiWordSuggestion(suggestion, 'replchars', allow_dash=False)
            else:
                yield Suggestion(suggestion, 'replchars')

        for words in pmt.twowords(word):
            yield Suggestion(' '.join(words), 'spaceword')

            if self.use_dash():
                # "alot" => "a-lot"
                yield Suggestion('-'.join(words), 'spaceword')

     
        for suggestion in pmt.mapchars(word, self.aff.MAP):
            yield Suggestion(suggestion, 'mapchars')

      
        for suggestion in pmt.swapchar(word):
            yield Suggestion(suggestion, 'swapchar')

     
        for suggestion in pmt.longswapchar(word):
            yield Suggestion(suggestion, 'longswapchar')

   
        for suggestion in pmt.badcharkey(word, self.aff.KEY):
            yield Suggestion(suggestion, 'badcharkey')

      
        for suggestion in pmt.extrachar(word):
            yield Suggestion(suggestion, 'extrachar')

       
        for suggestion in pmt.forgotchar(word, self.aff.TRY):
            yield Suggestion(suggestion, 'forgotchar')

      
        for suggestion in pmt.movechar(word):
            yield Suggestion(suggestion, 'movechar')

  
        for suggestion in pmt.badchar(word, self.aff.TRY):
            yield Suggestion(suggestion, 'badchar')

     
        for suggestion in pmt.doubletwochars(word):
            yield Suggestion(suggestion, 'doubletwochars')

        if not self.aff.NOSPLITSUGS:
           
            for suggestion_pair in pmt.twowords(word):
                yield MultiWordSuggestion(suggestion_pair, 'twowords', allow_dash=self.use_dash())

    def ngram_suggestions(self, word: str, handled: Set[str]) -> Iterator[str]:
        """
        Produces ngram-based suggestions, by passing to
        :meth:`ngram_suggest.ngram_suggest <spylls.hunspell.algo.ngram_suggest.ngram_suggest>` current
        misspelling, already found suggestions and settings from .aff file.

        See :mod:`ngram_suggest <spylls.hunspell.algo.ngram_suggest>`.

        Args:
            word: Misspelled word
            handled: List of already handled (known) suggestions; it is reused in
                     :meth:`ngram_suggest.filter_guesses <spylls.hunspell.algo.ngram_suggest.filter_guesses>`
                     to decide whether we add "not really good" ngram-based suggestions to result
        """
        if self.aff.MAXNGRAMSUGS == 0:
            return

        yield from ngram_suggest.ngram_suggest(
                    word.lower(),
                    dictionary_words=self.words_for_ngram,
                    prefixes=self.aff.PFX, suffixes=self.aff.SFX,
                    known={*(word.lower() for word in handled)},
                    maxdiff=self.aff.MAXDIFF,
                    onlymaxdiff=self.aff.ONLYMAXDIFF,
                    has_phonetic=(self.aff.PHONE is not None))

    def phonet_suggestions(self, word: str) -> Iterator[str]:
        """
        Produces phonetical similarity-based suggestions, by passing to
        :meth:`phonet_suggest.phonet_suggest <spylls.hunspell.algo.phonet_suggest.phonet_suggest>` current
        misspelling and settings from .aff file.

        See :mod:`phonet_suggest <spylls.hunspell.algo.phonet_suggest.phonet_suggest>`.

        Args:
            word: Misspelled word
        """
        if not self.aff.PHONE:
            return

        yield from phonet_suggest.phonet_suggest(word, dictionary_words=self.words_for_ngram, table=self.aff.PHONE)

    def use_dash(self) -> bool:
        """
        Yeah, that's how hunspell defines whether words can be split by dash in this language:
        either dash is explicitly mentioned in TRY directive, or TRY directive indicates the
        language uses Latinic script. So dictionaries omiting TRY directive, or for languages with,
        say, Cyrillic script not including "-" in it, will never suggest "foobar" => "foo-bar",
        even if it is the perfectly normal way to spell.
        """
        return '-' in self.aff.TRY or 'a' in self.aff.TRY
