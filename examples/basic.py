import pathlib
path = pathlib.Path(__file__).parent  / 'en_US'

from spylls.hunspell import Dictionary

dictionary = Dictionary.from_files(str(path))

print(dictionary.lookup('хариуцлага'))
print([*dictionary.suggest('бооор')])
