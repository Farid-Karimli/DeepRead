from papermage.predictors.base_predictors.base_predictor import BasePredictor
from papermage.predictors.base_predictors.hf_predictors import HFBIOTaggerPredictor
from papermage.predictors.block_predictors import LPEffDetPubLayNetBlockPredictor
from papermage.predictors.formula_predictors import LPEffDetFormulaPredictor
from papermage.predictors.sentence_predictors import PysbdSentencePredictor
from papermage.predictors.token_predictors import HFWhitspaceTokenPredictor
from papermage.predictors.vila_predictors import IVILATokenClassificationPredictor
from papermage.predictors.word_predictors import SVMWordPredictor

try:
    from papermage.predictors.span_qa_predictors import APISpanQAPredictor
except ModuleNotFoundError as e:
    if e.name != "decontext":
        raise
    import unittest

    class APISpanQAPredictor:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise unittest.SkipTest(
                "APISpanQAPredictor requires optional dependency `decontext`. "
                "Install with `pip install -e .[decontext]`."
            )

__all__ = [
    "HFBIOTaggerPredictor",
    "IVILATokenClassificationPredictor",
    "HFWhitspaceTokenPredictor",
    "SVMWordPredictor",
    "PysbdSentencePredictor",
    "LPEffDetPubLayNetBlockPredictor",
    "LPEffDetFormulaPredictor",
    "APISpanQAPredictor",
    "BasePredictor",
]
