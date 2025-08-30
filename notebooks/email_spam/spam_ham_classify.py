#!/usr/bin/env python3
"""
Classify emails from emails.txt using saved spam/ham model + vectorizer.
"""

import joblib
import os

# Load saved model/vectorizer
clf = joblib.load("spam_ham_model.pkl")
vectorizer = joblib.load("spam_ham_vectorizer.pkl")

# Preprocess function must match training
import string
import nltk
from nltk.corpus import stopwords
from nltk.stem.porter import PorterStemmer

def ensure_stopwords():
    try:
        _ = stopwords.words("english")
    except LookupError:
        nltk.download("stopwords")

ensure_stopwords()
stemmer = PorterStemmer()
stopwords_set = set(stopwords.words("english"))

def prepare_email_text(email_text: str) -> str:
    email_text = email_text.lower().translate(str.maketrans('', '', string.punctuation)).split()
    email_text = [stemmer.stem(w) for w in email_text if w not in stopwords_set]
    return " ".join(email_text)

# Load emails.txt
emails_path = "emails.txt"
if not os.path.isfile(emails_path):
    print("No emails.txt found")
    exit()

with open(emails_path, "r", encoding="utf-8") as f:
    email_data = [line.strip() for line in f if line.strip()]

# Predict
for text in email_data:
    processed = prepare_email_text(text)
    x_email = vectorizer.transform([processed])
    pred = clf.predict(x_email)[0]  # 0 = ham, 1 = spam
    preview = text[:100] + ("..." if len(text) > 100 else "")
    label = "spam" if pred == 1 else "ham"
    print(f"{label} ({pred}) → {preview}")
