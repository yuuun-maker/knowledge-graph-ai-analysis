# ⚠️ 这是 AI 预标注，不是人工抽样验证

本目录下的判定表由 **AI（Claude）** 逐条判读原文后填写，**不是人工判定结果**。

## 它是什么

- **用途**：① 验证 `calc_manual_accuracy.py` 在「判定列有值」时的汇总路径能正常跑通；
  ② 给人工判定者一个可对照的起点（可先看，再独立判，或直接复核并修正）。
- **范围**：前 30 条关系 + 前 15 个实体，其余留空（留空项不计入分母，汇总报告会单独披露条数）。

## 它不是什么

- **不能作为赛题「人工抽样验证」的结果。** 赛题要的是「人工」判定，AI 判读不属于人工。
  任何材料中都不得把本目录的数字写成「人工抽样准确率」。
- **不能替代人工判定。** 官方判定表在 `eval_data/manual_check/`，**未被本目录影响**，
  仍待人工逐条填写。

## 复核方式

```bash
cd backend
python scripts/calc_manual_accuracy.py \
    --out-dir eval_data/manual_check_ai \
    --json-out eval_data/manual_accuracy_ai_prelabel.json \
    --md-out eval_data/manual_accuracy_ai_prelabel.md
```

人工复核时，请**独立判读原文**再对照本结果；直接照抄会失去独立验证的意义。
若复核对某条不同意，以人工判定为准，并记录分歧条数——**分歧率本身是有价值的指标**
（它反映抽样判定标准是否足够明确）。
