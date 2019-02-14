"""Build Flair classifiers.

Usage:
  buildflair.py --in-reports=<infile> --in-classes=<classes> --prog-classifier=<classifier> --cancer-classifier=<classifier>

Options:
  --in-reports=<infile>             Input file with cleaned radiology reports (as generated by `cleaning.py`)
  --in-classes=<classes>            Input file with classification of radiology reports. Should have 3 columns: Id,Cancer,Progression
  --prog-classifier=<classifier>    Produced flair classifier for progression
  --cancer-classifier=<classifier>  Produced flair classifier for cancer
"""
from docopt import docopt

import pandas as pd
import chardet
import csv
import tempfile

from flair.data_fetcher import NLPTaskDataFetcher
from flair.embeddings import WordEmbeddings, FlairEmbeddings, DocumentLSTMEmbeddings
from flair.models import TextClassifier
from flair.trainers import ModelTrainer
from pathlib import Path

from tempfile import TemporaryDirectory

def trainFlairClassifier(df, columns, trainNameCsv, testNameCsv, devNameCsv, classifierFileName):
    ids = df['id'].tolist()

    nSamples = len(ids)
    idx80 = int(nSamples * 0.7)
    idx90 = int(nSamples * 0.9)

    train_ids = ids[:idx80]
    test_ids  = ids[idx80:idx90]
    dev_ids   = ids[idx90:]

    with TemporaryDirectory() as temp_dir:
        trainCsv = temp_dir + trainNameCsv
        testCsv  = temp_dir + testNameCsv
        devCsv   = temp_dir + devNameCsv

        df[df['id'].isin(train_ids)].to_csv(trainCsv, columns=columns, sep='\t', index=False, header=False)
        df[df['id'].isin(test_ids) ].to_csv(testCsv , columns=columns, sep='\t', index=False, header=False)
        df[df['id'].isin(dev_ids)  ].to_csv(devCsv  , columns=columns, sep='\t', index=False, header=False)

        corpus = NLPTaskDataFetcher.load_classification_corpus(temp_dir, train_file=trainCsv, test_file=testCsv, dev_file=devCsv)

        word_embeddings = [WordEmbeddings('glove'), FlairEmbeddings('news-forward-fast'), FlairEmbeddings('news-backward-fast')]
        document_embeddings = DocumentLSTMEmbeddings(word_embeddings, hidden_size=512, reproject_words=True, reproject_words_dimension=256)
        classifier = TextClassifier(document_embeddings, label_dictionary=corpus.make_label_dictionary(), multi_label=False)
        trainer = ModelTrainer(classifier, corpus)

        trainer.train(temp_dir, max_epochs=50)

        classifier.save(classifierFileName)


if __name__ == '__main__':
    arguments = docopt(__doc__)

    cleanDatafile = arguments['--in-reports']
    classesfile = arguments['--in-classes']
    progClassifierFileName = arguments['--prog-classifier']
    cancerClassifierFileName = arguments['--cancer-classifier']

    # Load reports and classification labels
    rawfile = open(cleanDatafile, 'rb').read()
    encodeInfo = chardet.detect(rawfile[:10000])
    df_cases = pd.read_csv(cleanDatafile, encoding=encodeInfo['encoding'], names=['id', 'normalized'])
    df_cases = df_cases.fillna('')
    df_classes = pd.read_csv(classesfile, sep=',', names=['ID', 'Cancer', 'Prog'])

    # Merge into single data frame
    df_unified = pd.merge(df_cases, df_classes, how='outer', left_on='id', right_on='ID')

    # We do not know if cases with multiple reports contain useful information
    # on the first report or the last one. So I will ignore these cases.
    # Keeping only cases with only 1 report
    df_counts = df_unified.groupby('id')['id'].count().reset_index(name="count")
    df_unified = pd.merge(df_unified, df_counts, how='outer', left_on='id', right_on='id')
    df_unified = df_unified[df_unified['count']==1].copy()

    # Discard unlabeled reports
    df_labeled = df_unified[df_unified['Cancer'].notna()].copy()

    # Convert labels to Flair format (Fast Text)
    df_labeled['Cancer'] = '__label__' + df_labeled['Cancer']
    df_labeled['Prog'] = '__label__' + df_labeled['Prog']

    # Train classifiers
    trainNameCsv = '/tr.csv'
    testNameCsv  = '/ts.csv'
    devNameCsv   = '/dv.csv'

    # Train progression classifier
    columns=['Prog', 'normalized']
    trainFlairClassifier(df_labeled, columns, trainNameCsv, testNameCsv, devNameCsv, progClassifierFileName)

    # Train cancer classifier
    columns=['Cancer', 'normalized']
    trainFlairClassifier(df_labeled, columns, trainNameCsv, testNameCsv, devNameCsv, cancerClassifierFileName)
