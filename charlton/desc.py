# This file is part of Charlton
# Copyright (C) 2011-2012 Nathaniel Smith <njs@pobox.com>
# See file COPYING for license information.

# This file defines the ModelDesc class, which describes a model at a high
# level, as a list of interactions of factors. It also has the code to convert
# a formula parse tree (from charlton.parse_formula) into a ModelDesc.

from charlton import CharltonError
from charlton.parse_formula import ParseNode, Token, parse_formula
from charlton.eval import EvalEnvironment, EvalFactor
from charlton.util import to_unique_tuple
from charlton.util import repr_pretty_delegate, repr_pretty_impl

# These are made available in the charlton.* namespace
__all__ = ["Term", "ModelDesc", "INTERCEPT", "LookupFactor"]

# One might think it would make more sense for 'factors' to be a set, rather
# than a tuple-with-guaranteed-unique-entries-that-compares-like-a-set. The
# reason we do it this way is that it preserves the order that the user typed
# and is expecting, which then ends up producing nicer names in our final
# output, nicer column ordering, etc. (A similar comment applies to the
# ordering of terms in ModelDesc objects as a whole.)
class Term(object):
    def __init__(self, factors):
        self.factors = to_unique_tuple(factors)

    def __eq__(self, other):
        return (isinstance(other, Term)
                and frozenset(other.factors) == frozenset(self.factors))

    def __hash__(self):
        return hash((Term, frozenset(self.factors)))

    __repr__ = repr_pretty_delegate
    def _repr_pretty_(self, p, cycle):
        assert not cycle
        repr_pretty_impl(p, self, [list(self.factors)])

    def name(self):
        if self.factors:
            return ":".join([f.name() for f in self.factors])
        else:
            return "Intercept"

INTERCEPT = Term([])

class LookupFactor(object):
    def __init__(self, name, origin=None):
        self._name = name
        self.origin = origin

    def name(self):
        return self._name

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._name)
       
    def __eq__(self, other):
        return isinstance(other, LookupFactor) and self._name == other._name

    def __hash__(self):
        return hash((LookupFactor, self._name))

    def memorize_passes_needed(self, state):
        return 0

    def memorize_chunk(self, state, which_pass, env): # pragma: no cover
        assert False

    def memorize_finish(self, state, which_pass): # pragma: no cover
        assert False

    def eval(self, memorize_state, data):
        return data[self._name]

def test_LookupFactor():
    l_a = LookupFactor("a")
    assert l_a.name() == "a"
    assert l_a == LookupFactor("a")
    assert l_a != LookupFactor("b")
    assert hash(l_a) == hash(LookupFactor("a"))
    assert hash(l_a) != hash(LookupFactor("b"))
    assert l_a.eval({}, {"a": 1}) == 1
    assert l_a.eval({}, {"a": 2}) == 2
    assert repr(l_a) == "LookupFactor('a')"
    assert l_a.origin is None
    l_with_origin = LookupFactor("b", origin="asdf")
    assert l_with_origin.origin == "asdf"

class _MockFactor(object):
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

def test_Term():
    assert Term([1, 2, 1]).factors == (1, 2)
    assert Term([1, 2]) == Term([2, 1])
    assert hash(Term([1, 2])) == hash(Term([2, 1]))
    f1 = _MockFactor("a")
    f2 = _MockFactor("b")
    assert Term([f1, f2]).name() == "a:b"
    assert Term([f2, f1]).name() == "b:a"
    assert Term([]).name() == "Intercept"

_builtins_dict = {}
exec "from charlton.builtins import *" in {}, _builtins_dict

class ModelDesc(object):
    def __init__(self, lhs_termlist, rhs_termlist):
        self.lhs_termlist = to_unique_tuple(lhs_termlist)
        self.rhs_termlist = to_unique_tuple(rhs_termlist)

    __repr__ = repr_pretty_delegate
    def _repr_pretty_(self, p, cycle):
        assert not cycle
        return repr_pretty_impl(p, self,
                                [],
                                [("lhs_termlist", list(self.lhs_termlist)),
                                 ("rhs_termlist", list(self.rhs_termlist))])

    def describe(self):
        def term_code(term):
            if term == INTERCEPT:
                return "1"
            else:
                return term.name()
        result = " + ".join([term_code(term) for term in self.lhs_termlist])
        if result:
            result += " ~ "
        else:
            result += "~ "
        if self.rhs_termlist == (INTERCEPT,):
            result += term_code(INTERCEPT)
        else:
            term_names = []
            if INTERCEPT not in self.rhs_termlist:
                term_names.append("0")
            term_names += [term_code(term) for term in self.rhs_termlist
                           if term != INTERCEPT]
            result += " + ".join(term_names)
        return result
            
    @classmethod
    def from_formula(cls, tree_or_string, factor_eval_env):
        if isinstance(tree_or_string, ParseNode):
            tree = tree_or_string
        else:
            tree = parse_formula(tree_or_string)
        factor_eval_env.add_outer_namespace(_builtins_dict)
        value = Evaluator(factor_eval_env).eval(tree, require_evalexpr=False)
        assert isinstance(value, cls)
        return value

def test_ModelDesc():
    f1 = _MockFactor("a")
    f2 = _MockFactor("b")
    m = ModelDesc([INTERCEPT, Term([f1])], [Term([f1]), Term([f1, f2])])
    assert m.lhs_termlist == (INTERCEPT, Term([f1]))
    assert m.rhs_termlist == (Term([f1]), Term([f1, f2]))
    print m.describe()
    assert m.describe() == "1 + a ~ 0 + a + a:b"

    assert ModelDesc([], []).describe() == "~ 0"
    assert ModelDesc([INTERCEPT], []).describe() == "1 ~ 0"
    assert ModelDesc([INTERCEPT], [INTERCEPT]).describe() == "1 ~ 1"
    assert (ModelDesc([INTERCEPT], [INTERCEPT, Term([f2])]).describe()
            == "1 ~ b")

def test_ModelDesc_from_formula():
    for input in ("y ~ x", parse_formula("y ~ x")):
        eval_env = EvalEnvironment.capture(0)
        md = ModelDesc.from_formula(input, eval_env)
        assert md.lhs_termlist == (Term([EvalFactor("y", eval_env)]),)
        assert md.rhs_termlist == (INTERCEPT, Term([EvalFactor("x", eval_env)]))

class IntermediateExpr(object):
    "This class holds an intermediate result while we're evaluating a tree."
    def __init__(self, intercept, intercept_origin, intercept_removed, terms):
        self.intercept = intercept
        self.intercept_origin = intercept_origin
        self.intercept_removed =intercept_removed
        self.terms = to_unique_tuple(terms)
        if self.intercept:
            assert self.intercept_origin
        assert not (self.intercept and self.intercept_removed)

    __repr__ = repr_pretty_delegate
    def _pretty_repr_(self, p, cycle): # pragma: no cover
        assert not cycle
        return repr_pretty_impl(p, self,
                                [self.intercept, self.intercept_origin,
                                 self.intercept_removed, self.terms])

def _maybe_add_intercept(doit, terms):
    if doit:
        return (INTERCEPT,) + terms
    else:
        return terms

def _eval_any_tilde(evaluator, tree):
    exprs = [evaluator.eval(arg) for arg in tree.args]    
    if len(exprs) == 1:
        # Formula was like: "~ foo"
        # We pretend that instead it was like: "0 ~ foo"
        exprs.insert(0, IntermediateExpr(False, None, True, []))
    assert len(exprs) == 2
    # Note that only the RHS gets an implicit intercept:
    return ModelDesc(_maybe_add_intercept(exprs[0].intercept, exprs[0].terms),
                     _maybe_add_intercept(not exprs[1].intercept_removed,
                                          exprs[1].terms))

def _eval_binary_plus(evaluator, tree):
    left_expr = evaluator.eval(tree.args[0])
    if tree.args[1].type == "ZERO":
        return IntermediateExpr(False, None, True, left_expr.terms)
    else:
        right_expr = evaluator.eval(tree.args[1])
        if right_expr.intercept:
            return IntermediateExpr(True, right_expr.intercept_origin, False,
                                    left_expr.terms + right_expr.terms)
        else:
            return IntermediateExpr(left_expr.intercept,
                                    left_expr.intercept_origin,
                                    left_expr.intercept_removed,
                                    left_expr.terms + right_expr.terms)
    

def _eval_binary_minus(evaluator, tree):
    left_expr = evaluator.eval(tree.args[0])
    if tree.args[1].type == "ZERO":
        return IntermediateExpr(True, tree.args[1], False,
                                left_expr.terms)
    elif tree.args[1].type == "ONE":
        return IntermediateExpr(False, None, True, left_expr.terms)
    else:
        right_expr = evaluator.eval(tree.args[1])
        terms = [term for term in left_expr.terms
                 if term not in right_expr.terms]
        if right_expr.intercept:
            return IntermediateExpr(False, None, True, terms)
        else:
            return IntermediateExpr(left_expr.intercept,
                                    left_expr.intercept_origin,
                                    left_expr.intercept_removed,
                                    terms)

def _check_interactable(expr):
    if expr.intercept:
        raise CharltonError("intercept term cannot interact with "
                            "anything else", expr.intercept_origin)

def _interaction(left_expr, right_expr):
    for expr in (left_expr, right_expr):
        _check_interactable(expr)
    terms = []
    for l_term in left_expr.terms:
        for r_term in right_expr.terms:
            terms.append(Term(l_term.factors + r_term.factors))
    return IntermediateExpr(False, None, False, terms)

def _eval_binary_prod(evaluator, tree):
    exprs = [evaluator.eval(arg) for arg in tree.args]
    return IntermediateExpr(False, None, False,
                            exprs[0].terms
                            + exprs[1].terms
                            + _interaction(*exprs).terms)

# Division (nesting) is right-ward distributive:
#   a / (b + c) -> a/b + a/c -> a + a:b + a:c
# But left-ward, in S/R it has a quirky behavior:
#   (a + b)/c -> a + b + a:b:c
# This is because it's meaningless for a factor to be "nested" under two
# different factors. (This is documented in Chambers and Hastie (page 30) as a
# "Slightly more subtle..." rule, with no further elaboration. Hopefully we
# will do better.)
def _eval_binary_div(evaluator, tree):
    left_expr = evaluator.eval(tree.args[0])
    right_expr = evaluator.eval(tree.args[1])
    terms = list(left_expr.terms)
    _check_interactable(left_expr)
    # Build a single giant combined term for everything on the left:
    left_factors = []
    for term in left_expr.terms:
        left_factors += list(term.factors)
    left_combined_expr = IntermediateExpr(False, None, False,
                                          [Term(left_factors)])
    # Then interact it with everything on the right:
    terms += list(_interaction(left_combined_expr, right_expr).terms)
    return IntermediateExpr(False, None, False, terms)

def _eval_binary_interact(evaluator, tree):
    exprs = [evaluator.eval(arg) for arg in tree.args]
    return _interaction(*exprs)

def _eval_binary_power(evaluator, tree):
    left_expr = evaluator.eval(tree.args[0])
    _check_interactable(left_expr)
    power = -1
    if tree.args[1].type in ("ONE", "NUMBER"):
        expr = tree.args[1].token.extra
        try:
            power = int(expr)
        except ValueError:
            pass
    if power < 1:
        raise CharltonError("'**' requires a positive integer", tree.args[1])
    all_terms = left_expr.terms
    big_expr = left_expr
    # Small optimization: (a + b)**100 is just the same as (a + b)**2.
    power = min(len(left_expr.terms), power)
    for i in xrange(1, power):
        big_expr = _interaction(left_expr, big_expr)
        all_terms = all_terms + big_expr.terms
    return IntermediateExpr(False, None, False, all_terms)

def _eval_unary_plus(evaluator, tree):
    return evaluator.eval(tree.args[0])

def _eval_unary_minus(evaluator, tree):
    if tree.args[0].type == "ZERO":
        return IntermediateExpr(True, tree.origin, False, [])
    elif tree.args[0].type == "ONE":
        return IntermediateExpr(False, None, True, [])
    else:
        raise CharltonError("Unary minus can only be applied to 1 or 0", tree)

def _eval_zero(evaluator, tree):
    return IntermediateExpr(False, None, True, [])
    
def _eval_one(evaluator, tree):
    return IntermediateExpr(True, tree.origin, False, [])

def _eval_number(evaluator, tree):
    raise CharltonError("numbers besides '0' and '1' are "
                        "only allowed with **", tree)

def _eval_python_expr(evaluator, tree):
    factor = EvalFactor(tree.token.extra, evaluator._factor_eval_env,
                        origin=tree.origin)
    return IntermediateExpr(False, None, False, [Term([factor])])

class Evaluator(object):
    def __init__(self, factor_eval_env):
        self._evaluators = {}
        self._factor_eval_env = factor_eval_env
        self.add_op("~", 2, _eval_any_tilde)
        self.add_op("~", 1, _eval_any_tilde)

        self.add_op("+", 2, _eval_binary_plus)
        self.add_op("-", 2, _eval_binary_minus)
        self.add_op("*", 2, _eval_binary_prod)
        self.add_op("/", 2, _eval_binary_div)
        self.add_op(":", 2, _eval_binary_interact)
        self.add_op("**", 2, _eval_binary_power)

        self.add_op("+", 1, _eval_unary_plus)
        self.add_op("-", 1, _eval_unary_minus)

        self.add_op("ZERO", 0, _eval_zero)
        self.add_op("ONE", 0, _eval_one)
        self.add_op("NUMBER", 0, _eval_number)
        self.add_op("PYTHON_EXPR", 0, _eval_python_expr)

        # Not used by Charlton -- provided for the convenience of eventual
        # user-defined operators.
        self.stash = {}

    # This should not be considered a public API yet (to use for actually
    # adding new operator semantics) because I wrote in some of the relevant
    # code sort of speculatively, but it isn't actually tested.
    def add_op(self, op, arity, evaluator):
        self._evaluators[op, arity] = evaluator

    def eval(self, tree, require_evalexpr=True):
        result = None
        assert isinstance(tree, ParseNode)
        key = (tree.type, len(tree.args))
        if key not in self._evaluators:
            raise CharltonError("I don't know how to evaluate this "
                                "'%s' operator" % (tree.type,),
                                tree.token)
        result = self._evaluators[key](self, tree)
        if require_evalexpr and not isinstance(result, IntermediateExpr):
            if isinstance(result, ModelDesc):
                raise CharltonError("~ can only be used once, and "
                                    "only at the top level",
                                    tree)
            else:
                raise CharltonError("custom operator returned an "
                                    "object that I don't know how to "
                                    "handle", tree)
        return result

#############

_eval_tests = {
    "": (True, []),
    " ": (True, []),
    " \n ": (True, []),
    "a": (True, ["a"]),

    "1": (True, []),
    "0": (False, []),
    "- 1": (False, []),
    "- 0": (True, []),
    "+ 1": (True, []),
    "+ 0": (False, []),
    "0 + 1": (True, []),
    "1 + 0": (False, []),
    "1 - 0": (True, []),
    "0 - 1": (False, []),
    
    "1 + a": (True, ["a"]),
    "0 + a": (False, ["a"]),
    "a - 1": (False, ["a"]),
    "a - 0": (True, ["a"]),
    "1 - a": (True, []),

    "a + b": (True, ["a", "b"]),
    "(a + b)": (True, ["a", "b"]),
    "a + ((((b))))": (True, ["a", "b"]),
    "a + ((((+b))))": (True, ["a", "b"]),
    "a + ((((b - a))))": (True, ["a", "b"]),

    "a + a + a": (True, ["a"]),

    "a + (b - a)": (True, ["a", "b"]),

    "a + np.log(a, base=10)": (True, ["a", "np.log(a, base=10)"]),
    # Note different spacing:
    "a + np.log(a, base=10) - np . log(a , base = 10)": (True, ["a"]),
    
    "a + (I(b) + c)": (True, ["a", "I(b)", "c"]),
    "a + I(b + c)": (True, ["a", "I(b + c)"]),

    "a:b": (True, [("a", "b")]),
    "a:b:a": (True, [("a", "b")]),
    "a:(b + c)": (True, [("a", "b"), ("a", "c")]),
    "(a + b):c": (True, [("a", "c"), ("b", "c")]),
    "a:(b - c)": (True, [("a", "b")]),
    "c + a:c + a:(b - c)": (True, ["c", ("a", "c"), ("a", "b")]),
    "(a - b):c": (True, [("a", "c")]),
    "b + b:c + (a - b):c": (True, ["b", ("b", "c"), ("a", "c")]),

    "a:b - a:b": (True, []),
    "a:b - b:a": (True, []),

    "1 - (a + b)": (True, []),
    "a + b - (a + b)": (True, []),

    "a * b": (True, ["a", "b", ("a", "b")]),
    "a * b * a": (True, ["a", "b", ("a", "b")]),
    "a * (b + c)": (True, ["a", "b", "c", ("a", "b"), ("a", "c")]),
    "(a + b) * c": (True, ["a", "b", "c", ("a", "c"), ("b", "c")]),
    "a * (b - c)": (True, ["a", "b", ("a", "b")]),
    "c + a:c + a * (b - c)": (True, ["c", ("a", "c"), "a", "b", ("a", "b")]),
    "(a - b) * c": (True, ["a", "c", ("a", "c")]),
    "b + b:c + (a - b) * c": (True, ["b", ("b", "c"), "a", "c", ("a", "c")]),

    "a/b": (True, ["a", ("a", "b")]),
    "(a + b)/c": (True, ["a", "b", ("a", "b", "c")]),
    "b + b:c + (a - b)/c": (True, ["b", ("b", "c"), "a", ("a", "c")]),
    "a/(b + c)": (True, ["a", ("a", "b"), ("a", "c")]),

    "a ** 2": (True, ["a"]),
    "(a + b + c + d) ** 2": (True, ["a", "b", "c", "d",
                                    ("a", "b"), ("a", "c"), ("a", "d"),
                                    ("b", "c"), ("b", "d"), ("c", "d")]),
    "(a + b + c + d) ** 3": (True, ["a", "b", "c", "d",
                                    ("a", "b"), ("a", "c"), ("a", "d"),
                                    ("b", "c"), ("b", "d"), ("c", "d"),
                                    ("a", "b", "c"), ("a", "b", "d"),
                                    ("a", "c", "d"), ("b", "c", "d")]),

    "a + +a": (True, ["a"]),

    "~ a + b": (True, ["a", "b"]),
    "~ a*b": (True, ["a", "b", ("a", "b")]),
    "~ a*b + 0": (False, ["a", "b", ("a", "b")]),
    "~ -1": (False, []),

    "0 ~ a + b": (True, ["a", "b"]),
    "1 ~ a + b": (True, [], True, ["a", "b"]),
    "y ~ a + b": (False, ["y"], True, ["a", "b"]),
    "0 + y ~ a + b": (False, ["y"], True, ["a", "b"]),
    "0 + y * z ~ a + b": (False, ["y", "z", ("y", "z")], True, ["a", "b"]),
    "-1 ~ 1": (False, [], True, []),
    "1 + y ~ a + b": (True, ["y"], True, ["a", "b"]),

    # Check precedence:
    "a + b * c": (True, ["a", "b", "c", ("b", "c")]),
    "a * b + c": (True, ["a", "b", ("a", "b"), "c"]),
    "a * b - a": (True, ["b", ("a", "b")]),
    "a + b / c": (True, ["a", "b", ("b", "c")]),
    "a / b + c": (True, ["a", ("a", "b"), "c"]),
    "a*b:c": (True, ["a", ("b", "c"), ("a", "b", "c")]),
    "a:b*c": (True, [("a", "b"), "c", ("a", "b", "c")]),

    # Intercept handling:
    "~ 1 + 1 + 0 + 1": (True, []),
    "~ 0 + 1 + 0": (False, []),
    "~ 0 - 1 - 1 + 0 + 1": (True, []),
    "~ 1 - 1": (False, []),
    "~ 0 + a + 1": (True, ["a"]),
    "~ 1 + (a + 0)": (True, ["a"]), # This is correct, but perhaps surprising!
    "~ 0 + (a + 1)": (True, ["a"]), # Also correct!
    "~ 1 - (a + 1)": (False, []),
}

# <> mark off where the error should be reported:
_eval_error_tests = [
    "a <+>",
    "a + <(>",

    "b + <(-a)>",

    "a:<1>",
    "(a + <1>)*b",

    "a + <2>",
    "a + <1.0>",
    # eh, catching this is a hassle, we'll just leave the user some rope if
    # they really want it:
    #"a + <0x1>",

    "a ** <b>",
    "a ** <(1 + 1)>",
    "a ** <1.5>",

    "a + b <# asdf>",

    "<)>",
    "a + <)>",
    "<*> a",
    "a + <*>",

    "a + <foo[bar>",
    "a + <foo{bar>",
    "a + <foo(bar>",

    "a + <[bar>",
    "a + <{bar>",

    "a + <{bar[]>",

    "a + foo<]>bar",
    "a + foo[]<]>bar",
    "a + foo{}<}>bar",
    "a + foo<)>bar",

    "a + b<)>",
    "(a) <.>",

    "<(>a + b",

    "<y ~ a> ~ b",
    "y ~ <(a ~ b)>",
    "<~ a> ~ b",
    "~ <(a ~ b)>",

    "1 + <-(a + b)>",

    "<- a>",
    "a + <-a**2>",
]

def _assert_terms_match(terms, expected_intercept, expecteds, eval_env): # pragma: no cover
    if expected_intercept:
        expecteds = [()] + expecteds
    assert len(terms) == len(expecteds)
    for term, expected in zip(terms, expecteds):
        if isinstance(term, Term):
            if isinstance(expected, str):
                expected = (expected,)
            assert term.factors == tuple([EvalFactor(s, eval_env)
                                          for s in expected])
        else:
            assert term == expected

def _do_eval_formula_tests(tests): # pragma: no cover
    for code, result in tests.iteritems():
        if len(result) == 2:
            result = (False, []) + result
        eval_env = EvalEnvironment.capture(0)
        model_desc = ModelDesc.from_formula(code, eval_env)
        print repr(code)
        print result
        print model_desc
        lhs_intercept, lhs_termlist, rhs_intercept, rhs_termlist = result
        _assert_terms_match(model_desc.lhs_termlist,
                            lhs_intercept, lhs_termlist,
                            eval_env)
        _assert_terms_match(model_desc.rhs_termlist,
                            rhs_intercept, rhs_termlist,
                            eval_env)

def test_eval_formula():
    _do_eval_formula_tests(_eval_tests)

def test_eval_formula_error_reporting():
    from charlton.parse_formula import _parsing_error_test
    parse_fn = lambda formula: ModelDesc.from_formula(formula,
                                                      EvalEnvironment.capture(0))
    _parsing_error_test(parse_fn, _eval_error_tests)

def test_formula_factor_origin():
    from charlton.origin import Origin
    desc = ModelDesc.from_formula("a + b", EvalEnvironment.capture(0))
    assert (desc.rhs_termlist[1].factors[0].origin
            == Origin("a + b", 0, 1))
    assert (desc.rhs_termlist[2].factors[0].origin
            == Origin("a + b", 4, 5))
    
