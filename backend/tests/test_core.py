import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from app.main import classify, topics

def test_classify_dbms():
    assert classify('DBMS_unit3.pdf','normalization and BCNF')[0]=='College'

def test_topics():
    assert 'Normalization' in topics('Normalization and 3NF','dbms.pdf')
