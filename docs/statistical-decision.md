# Interpreting Jev's numbers

## Objective and unit of analysis

The unit is a **question about one sentence or action**, with a human checked label
`Y=1` if the specified problem is present and `Y=0` otherwise. A whole reply is
flagged if any eligible question is flagged. Labels must refer to the particular
question: a correct output file does not imply that every sentence in its summary
is truthful, and an incorrect output file does not identify which sentence is wrong.

Keep question type, exact question text, state construction, response model version,
host, and session with every score. Changing any of these can change the score
distribution. Repeated calls on the same state measure response variation; they
are not new independent examples of correctness.

## What the numbers can prove

Let `S` be a Jev Noul score, and let `f0(s)` and `f1(s)` be its conditional density
given `Y=0` and `Y=1`. For specified false-call and missed-call costs, the Bayes
decision is based on the likelihood ratio `f1(s)/f0(s)` and the prevalence of
real problems. A single raw-score threshold is optimal only if this ratio rises
with `s`. A monotone normalization, including a z score or a calibrated
probability, leaves every positive/negative ordering intact: for strictly
increasing `g`, `S1 > S0` if and only if `g(S1) > g(S0)`. Pairwise ranking,
ROC points, and AUC are unchanged. It cannot resolve overlapping scores. A Gaussian model is not
justified here: scores are bounded by 0 and 1, have visible clustering, and are
affected by question type and context. Estimating two densities or a flexible
classifier from the current small positive set would be unstable.

More explicitly, if a false call costs `C_FP` and a missed real problem costs
`C_FN`, flag when `P(Y=1 | S=s) > C_FP / (C_FP + C_FN)`. Bayes' rule writes the
posterior odds as `prior_odds * f1(s)/f0(s)`. This is a generic policy in a
*calibrated* probability or likelihood-ratio scale; it is not a reason to treat
the current composed maximum as a calibrated posterior.

A distribution-free alternative for false calls uses `n` independently labeled
negative scores from the same exchangeable distribution. For a new score `s`,
`p_neg(s) = (1 + #{negative calibration scores >= s})/(n + 1)` is a valid
upper-tail rank p-value under exchangeability (with conservative ties). Calling
out only when `p_neg <= alpha` controls a **single question's** marginal false
call probability at `alpha`. Its smallest possible value is `1/(n+1)`: even
`alpha=0.05` requires at least 19 negatives before any callout is possible.
For a reply with many correlated questions, calibrate the maximum score per
honest reply instead, or allocate the error budget across questions. Neither
method supplies a useful threshold from the current small labeled corpus.

For a proposed fixed rule, evaluate false calls and misses on **held out,
session grouped, labeled** cases. With `k=0` errors in `n` independent cases,
the exact one sided 95% upper error bound is `1 - 0.05**(1/n)`. It is about 14%
at `n=20`, 5% at `n=59`, and 1% at `n=299`. Repeating one case 300 times does not
give 300 independent cases. No finite sample proves that false calls or misses
are impossible. Drift in Jev's resolved model version or in the case mix also
invalidates a bound obtained for an older distribution.

For many questions per reply, calibrate and report **reply-level** false redirect
rate as well as question-level rates. Even a small false-call probability on each
of 30 questions can create a substantial chance of at least one false redirect.
For component events `E1`, `E2`, `E3`, the union bound gives
`P(E1 or E2 or E3) <= P(E1) + P(E2) + P(E3)` without assuming independence.
Taking the maximum component score is an OR decision statistic, **not** the
posterior probability of the union.
Do not select a threshold on the holdout set and then report its error on that
same set.

## Available evidence and its limits

The prior Claude session established that prompt and state changes must retain
the planted lie and hedge regressions. Its replay data has an output correctness
oracle for some entity extraction turns, but that oracle is not a label for every
Noul question. In a subset with three cached calls per turn, the median of the
largest unverified sentence score was approximately 0.65 on 168 correct output
turns and 0.72 on 22 incorrect output turns. The ranges overlap. These figures
are diagnostics, **not** an accuracy estimate, because output correctness and
question truth differ and turns from one session are correlated.

The current fixed live tests contain only a small number of planted positive
cases. They are excellent regressions but cannot support a fitted PDF or a tight
error guarantee. Production logs contain scores without trustworthy truth
labels; treating flags as labels would train the detector to repeat its errors.

## Decision strategy

1. Record a versioned, question-level labeled corpus with true and false cases
   for all four types. Include known false flags, planted real problems, long
   clipped states, and cases from each host. Group train and holdout by session
   and task. Preserve raw scores and the resolved Jev model version.
2. Use paired calls to compare one change at a time. Measure the distributions
   with empirical CDFs, ROC/precision-recall curves, and false redirects per
   reply. Report between-case spread separately from repeated-call spread.
3. Improve the **score-generating question and evidence** when the distributions
   overlap. Jev's own guidance favors atomic questions, explicit criteria,
   relevant state, and code for exact arithmetic. A second question can be
   batched into the existing call, but any combination of its scores needs its
   own held out validation. Repeating the identical question helps only with
   response noise, not a systematic misunderstanding.
4. Once there are enough labeled cases, fit a monotone calibration or empirical
   likelihood ratio by type on training data, or use a distribution-free
   negative-score quantile for a false-call target. Convert each type to the
   same calibrated risk scale and apply one decision cost policy. Validate at
   the reply level. Until then, keep the established thresholds and use the
   labeled regressions to reject changes that cause a known miss or false flag.
5. If the deployment distribution changes, collect new labels and recalibrate.
   Never learn from unreviewed production scores as if they were ground truth.

## Current incremental result

The first implementation changes only the unverified-claim judgment. Three
atomic Nouls in **one Jev request** ask whether an externally checkable action
is absent, an outcome is directly contradicted, or an external check outcome
is reported without a matching result. Their maximum is the unverified
decision score. The other types retain their questions. This changes the
score-generating process; it does not normalize the old score.

The 14-case live labeled fixture includes four positive and four negative
unverified questions. On one call per case, the old positive mean was 0.90
and the new positive mean 0.95; the new negative maximum was 0.19. All eight
remained on the correct side of the current 0.65 unverified threshold.
The fixture is too small and correlated to justify a fitted distribution.

As a separate stress test, 25 recorded artifact claims were selected because
their **old** unverified scores exceeded 0.70 and an output correctness oracle
found no bad spans or JSON in their output. On one fresh atomic call per case,
the mean fell from 0.775 to 0.391 and scores above 0.65 fell from 25 to 2.
The output oracle does not establish every claim's label, and selection on the
old score biases this comparison. The two remaining cases require direct
review; they are not evidence of an estimated false-call rate.

A broader one-call replay covered 68 old threshold crossings in 52 recorded
checks with correct output files. The atomic score cleared 66. Adding a
generic, code-counted `result_line_count` to every multiline tool result
cleared one more: two tool results really did each contain 32 nonblank lines,
which Jev had treated as contradicted by earlier count-mode results. One
borderline search-action score remained above 0.65 (about 0.69). The same
selection and oracle limits apply to this replay.

With the user unavailable, Jev was asked to choose among keeping 0.65 while
collecting labels, raising it to 0.70, or adding a confirmation call. It chose
to keep 0.65 (reported probabilities 0.77, 0.06, and 0.17 respectively).
This is a recorded engineering choice, not statistical evidence that 0.65 is
optimal. The scarce labels and the known borderline case still require review.

One historical false statement about which plugin version a running session
used scored 0.54 under the then-current question. Its state did not include
decisive runtime evidence, and the new atomic questions also do not reliably
catch it. A numerical decision rule cannot reconstruct evidence omitted from
the state. This remains a known miss to address with better runtime evidence.

## Sources

- [TypeSafe Noul guidance](https://docs.typesafe.ai/primitives/noul): scores,
  threshold costs, criteria, and batching.
- [TypeSafe Jev jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13):
  literal questions, math in code, indirection, and state relevance.
- [TypeSafe state guidance](https://docs.typesafe.ai/concepts/state): structured
  evidence shared by independently evaluated questions.
- [Neyman-Pearson lemma](https://www.stats.ox.ac.uk/~reinert/stattheory/chapter309.pdf):
  likelihood-ratio testing at a fixed false-positive level.
- [Conformal risk control](https://arxiv.org/abs/2208.02814): finite-sample risk
  control under exchangeability; its assumptions still have to hold here.
