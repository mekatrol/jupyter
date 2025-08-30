#!/usr/bin/env python3
"""
Train spam/ham classifier and save model + vectorizer to disk.
"""

import os
import string
import joblib
import pandas as pd
import nltk
from nltk.corpus import stopwords
from nltk.stem.porter import PorterStemmer
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier

# ---------- Helpers ----------

def ensure_stopwords():
    try:
        _ = stopwords.words("english")
    except LookupError:
        nltk.download("stopwords")

def build_preprocessor():
    stemmer = PorterStemmer()
    stopwords_set = set(stopwords.words("english"))

    def prepare_email_text(email_text: str) -> str:
        email_text = email_text.lower().translate(str.maketrans('', '', string.punctuation)).split()
        email_text = [stemmer.stem(w) for w in email_text if w not in stopwords_set]
        return " ".join(email_text)

    return prepare_email_text

# ---------- Training ----------

def main():
    ensure_stopwords()
    prepare_email_text = build_preprocessor()

    # Load dataset
    df = pd.read_csv("spam_ham_dataset.csv")
    df["text"] = df["text"].astype(str).apply(lambda x: x.replace("\r\n", " "))

    # Build corpus
    corpus = [prepare_email_text(t) for t in df["text"]]

    # Vectorize
    vectorizer = CountVectorizer()
    X = vectorizer.fit_transform(corpus).toarray()
    y = df["label_num"].values

    # Split train/test
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    # Train classifier
    clf = RandomForestClassifier(n_jobs=-1, random_state=42)
    clf.fit(X_train, y_train)

    # Report accuracy
    acc = clf.score(X_test, y_test)
    print(f"Test accuracy: {acc:.4f}")

    # Save model + vectorizer
    joblib.dump(clf, "spam_ham_model.pkl")
    joblib.dump(vectorizer, "spam_ham_vectorizer.pkl")
    print("Saved spam_ham_model.pkl and spam_ham_vectorizer.pkl")

if __name__ == "__main__":
    main()
