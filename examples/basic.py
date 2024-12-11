from flask import Flask, render_template, request
import pathlib
from spylls.hunspell import Dictionary

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def spellchecker():
    path = pathlib.Path(__file__).parent / 'en_US' 
    dictionary = Dictionary.from_files(str(path))

    text = ''
    mistakes = []
    suggestions = []
    total_words = 0
    total_mistakes = 0
    total_letters = 0

    if request.method == 'POST':
        text = request.form['text'] 


        text_cleaned = text.translate(str.maketrans('', '', '.,'))
        

        total_letters = sum(c.isalpha() for c in text_cleaned)
        if total_letters > 300:
            return render_template('spellchecker.html', text=text, error="Text exceeds 300 letters limit.")

        words = text_cleaned.split()
        total_words = len(words) 

        for word in words:
            lookup_result = dictionary.lookup(word)
            if not lookup_result: 
                mistakes.append(word)
                suggestion_list = dictionary.suggest(word)
                suggestions.append((word, suggestion_list)) 
                total_mistakes += 1 

    return render_template('spellchecker.html', text=text, mistakes=mistakes, suggestions=suggestions, 
                           total_words=total_words, total_mistakes=total_mistakes, total_letters=total_letters)

if __name__ == '__main__':
    app.run(debug=True)
