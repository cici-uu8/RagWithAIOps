# 多栏版式 PDF baseline 样本

## 样本

| 文件 | 类型 | 来源 | 用途 |
|---|---|---|---|
| `N19-1423_bert_pretraining_two_column.pdf` | 多栏论文 PDF | ACL Anthology `N19-1423` | P0 PDF parser baseline 的多栏版式样本 |

## 来源

- 页面: https://aclanthology.org/N19-1423/
- PDF: https://aclanthology.org/N19-1423.pdf
- 文件名: `N19-1423_bert_pretraining_two_column.pdf`

## 本地验证

```text
file: PDF document, version 1.3, 16 pages
pdfinfo Title: BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding
pdfinfo Pages: 16
pdfinfo Creator: LaTeX with hyperref package
pdfinfo Producer: pdfTeX-1.40.18
pdfinfo Encrypted: no
sha256: 987545ffb087f1ece898142c403a516baeabeb70ce19089397fac6f7db12c3d4
```

## 使用规则

- 这个文件只作为 PDF 解析、多栏版式、页码和文本层 baseline 样本。
- 不把它当作业务知识库资料或 CRRC 业务资料。
- baseline manifest 中 `sample_type` 使用 `multi_column_pdf`。
- `pdftotext -layout -f 2 -l 2` 已能抽出左右栏并排正文，可用于多栏版式回归。
