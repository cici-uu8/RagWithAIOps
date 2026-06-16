"""ChunkPolicyService - 统一最终 chunk 边界规则的收口层。

输入: 上游产出的 ChunkRecord 列表 (来自 plain_text splitter 或 mineru ArtifactChunkBuilder)。
输出:
- ``apply()``: 仅返回最终子块列表，不生成父块。保持向后兼容。
- ``apply_with_parents()``: 返回 ``ChunkPolicyResult(chunks, parents)``，其中
  ``chunks`` 是最终子块（命中过 parent 的子块带 ``parent_chunk_id``），
  ``parents`` 是同 ``heading_path`` 下连续 ≥2 个文本子块聚合而成的章节级父块。

规则:
- 跨 heading_path 不合并普通正文。
- 同 heading_path 下的相邻短正文若合并后不超过 chunk_max_size 则合并。
- 普通正文超过 chunk_max_size 时按句界优先、长度兜底再拆。
- 表格 / 公式等非文本类型保持原子，不参与合并和再拆。
- chunk_index 按最终顺序重新编号 0..N-1。
- 边界发生变化的 chunk 重新生成 chunk_id 为 `{doc_id}:cp{new_index:05d}`，
  并同步刷新 source_ref.chunk_id / metadata.chunk_id / metadata.source_ref.chunk_id；
  边界未变的 chunk 保留原 chunk_id。
- 父块 chunk_id 为 ``{doc_id}:parent:{seq:05d}``，``content_type="section_parent"``，
  ``metadata.chunk_role="parent"``。父块仅落 metadata store，不写入向量库。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from app.config import config
from app.models import ChunkRecord


TEXT_CONTENT_TYPES = {"text", "markdown_section"}
SECTION_PARENT_CONTENT_TYPE = "section_parent"
SENTENCE_END_PATTERN = re.compile(r"[。！？!?]")
MERGE_SEPARATOR = "\n\n"
ATOMIC_HARD_CAP_DEFAULT_BYTES = 6000
ATOMIC_SPLIT_QUALITY_FLAG = "atomic_split_by_size"


@dataclass
class _WorkingChunk:
    chunk: ChunkRecord
    boundary_changed: bool


@dataclass
class ChunkPolicyResult:
    """统一 chunk policy 输出。

    Attributes:
        chunks: 最终子块。命中过父块的子块在 ``parent_chunk_id`` 与
            ``metadata['parent_chunk_id']`` 上携带父块 id；其余子块保持 ``None``。
        parents: 由同 heading_path 连续 ≥2 个文本子块聚合的章节级父块。
            ``parents`` 仅用于检索时回溯上下文，不应写入向量库。
    """

    chunks: list[ChunkRecord] = field(default_factory=list)
    parents: list[ChunkRecord] = field(default_factory=list)


class ChunkPolicyService:
    """统一 chunk 边界生成层。"""

    def __init__(self, chunk_max_size: int | None = None, atomic_hard_cap_bytes: int | None = None):
        # 默认对齐 DocumentSplitterService 的有效硬上限 (chunk_max_size * 2)，
        # 让现有 splitter 产物在 P2 切入时表现为 noop pass-through。
        self.chunk_max_size = (
            chunk_max_size if chunk_max_size is not None else config.chunk_max_size * 2
        )
        # 原子类型 (manual_table / command_table / equation_interline 等) 默认绕过
        # merge / resplit；当原文超 atomic_hard_cap_bytes 时仍按 byte-aware
        # codepoint-safe 切分，单位与 Milvus content varchar(8000) 对齐，
        # 避免中文 UTF-8 多字节展开后撞穿 schema 上限。详见
        # docs/chunk_policy_atomic_hardcap_design.md。
        self.atomic_hard_cap_bytes = (
            atomic_hard_cap_bytes
            if atomic_hard_cap_bytes is not None
            else ATOMIC_HARD_CAP_DEFAULT_BYTES
        )

    def apply(self, chunks: List[ChunkRecord]) -> List[ChunkRecord]:
        """旧接口：只返回最终子块，不生成父块。"""
        return self._apply(chunks, build_parents=False).chunks

    def apply_with_parents(self, chunks: List[ChunkRecord]) -> ChunkPolicyResult:
        """新接口：返回最终子块 + 章节级父块。"""
        return self._apply(chunks, build_parents=True)

    def _apply(self, chunks: List[ChunkRecord], build_parents: bool) -> ChunkPolicyResult:
        if not chunks:
            return ChunkPolicyResult()
        workings = [_WorkingChunk(chunk=c, boundary_changed=False) for c in chunks]
        workings = self._merge_pass(workings)
        workings = self._resplit_pass(workings)
        workings = self._atomic_hardcap_pass(workings)
        finalized = self._finalize(workings)
        if not build_parents:
            return ChunkPolicyResult(chunks=finalized, parents=[])
        parents = self._build_section_parents(finalized)
        if not parents:
            return ChunkPolicyResult(chunks=finalized, parents=[])
        linked = self._link_children_to_parents(finalized, parents)
        return ChunkPolicyResult(chunks=linked, parents=parents)

    def _merge_pass(self, workings: List[_WorkingChunk]) -> List[_WorkingChunk]:
        merged: List[_WorkingChunk] = []
        for working in workings:
            if not merged:
                merged.append(working)
                continue
            prev = merged[-1]
            if self._can_merge(prev.chunk, working.chunk):
                merged[-1] = _WorkingChunk(
                    chunk=self._merge_two(prev.chunk, working.chunk),
                    boundary_changed=True,
                )
            else:
                merged.append(working)
        return merged

    def _can_merge(self, prev: ChunkRecord, cur: ChunkRecord) -> bool:
        if prev.content_type not in TEXT_CONTENT_TYPES:
            return False
        if cur.content_type not in TEXT_CONTENT_TYPES:
            return False
        if list(prev.heading_path) != list(cur.heading_path):
            return False
        combined = len(prev.content) + len(MERGE_SEPARATOR) + len(cur.content)
        return combined <= self.chunk_max_size

    def _merge_two(self, prev: ChunkRecord, cur: ChunkRecord) -> ChunkRecord:
        new_content = prev.content + MERGE_SEPARATOR + cur.content
        page_starts = [p for p in (prev.page_start, cur.page_start) if p is not None]
        page_ends = [p for p in (prev.page_end, cur.page_end) if p is not None]
        merged_quality = sorted(set(prev.quality_flags) | set(cur.quality_flags))
        return prev.model_copy(
            update={
                "content": new_content,
                "end_index": prev.start_index + len(new_content),
                "page_start": min(page_starts) if page_starts else None,
                "page_end": max(page_ends) if page_ends else None,
                "quality_flags": merged_quality,
            }
        )

    def _resplit_pass(self, workings: List[_WorkingChunk]) -> List[_WorkingChunk]:
        out: List[_WorkingChunk] = []
        for working in workings:
            chunk = working.chunk
            if chunk.content_type not in TEXT_CONTENT_TYPES:
                out.append(working)
                continue
            if len(chunk.content) <= self.chunk_max_size:
                out.append(working)
                continue
            pieces = self._split_text(chunk.content)
            cursor = chunk.start_index
            for piece_text in pieces:
                piece_chunk = chunk.model_copy(
                    update={
                        "content": piece_text,
                        "start_index": cursor,
                        "end_index": cursor + len(piece_text),
                    }
                )
                cursor += len(piece_text)
                out.append(_WorkingChunk(chunk=piece_chunk, boundary_changed=True))
        return out

    def _split_text(self, text: str) -> List[str]:
        sentences = self._split_into_sentences(text)
        if len(sentences) == 1 and len(sentences[0]) > self.chunk_max_size:
            return self._hard_cut(text)

        pieces: List[str] = []
        buffer = ""
        for sentence in sentences:
            if len(sentence) > self.chunk_max_size:
                if buffer:
                    pieces.append(buffer)
                    buffer = ""
                pieces.extend(self._hard_cut(sentence))
                continue
            if len(buffer) + len(sentence) > self.chunk_max_size:
                pieces.append(buffer)
                buffer = sentence
            else:
                buffer += sentence
        if buffer:
            pieces.append(buffer)
        return pieces

    def _split_into_sentences(self, text: str) -> List[str]:
        boundaries = [match.end() for match in SENTENCE_END_PATTERN.finditer(text)]
        if not boundaries:
            return [text]
        sentences: List[str] = []
        cursor = 0
        for boundary in boundaries:
            sentences.append(text[cursor:boundary])
            cursor = boundary
        if cursor < len(text):
            sentences.append(text[cursor:])
        return sentences

    def _hard_cut(self, text: str) -> List[str]:
        return [text[i : i + self.chunk_max_size] for i in range(0, len(text), self.chunk_max_size)]

    def _atomic_hardcap_pass(self, workings: List[_WorkingChunk]) -> List[_WorkingChunk]:
        """统一硬上限保护：任何 content_type 超 atomic_hard_cap_bytes 都按 UTF-8
        字节长度切分，单位与 Milvus content varchar(8000) 对齐。

        text / markdown_section 经 _resplit_pass 已 ≤ chunk_max_size (字符)，
        本 pass 通常不再触动它们；主要受影响的是 manual_table / command_table /
        equation_interline 等原子类型——P2 设计让它们绕过 merge / resplit，原文
        多长就透传多长，写入 Milvus 时若 UTF-8 展开后超 8000 bytes 会被拒收。

        切分规则:
        - 按 UTF-8 字节长度判定是否超 cap，与 Milvus schema 同单位。
        - codepoint-safe: 不在 UTF-8 多字节序列中间断开。
        - 优先按 line 边界 greedy pack 多行到一片（保留表格行 / 公式行结构）；
          单行超 cap 时按 codepoint-aware 字节硬切兜底（不做 sentence 切分，
          atomic 类型 sentence 概念不适用）。
        - 不变 content_type、heading_path、pages、其他 metadata 字段 (model_copy 继承)。
        - quality_flags 加入 ``atomic_split_by_size`` 后取并集排序。
        - boundary_changed=True，让 _finalize 赋新 ``:cp{index:05d}`` chunk_id。
        """
        cap = self.atomic_hard_cap_bytes
        out: List[_WorkingChunk] = []
        for working in workings:
            chunk = working.chunk
            if len(chunk.content.encode("utf-8")) <= cap:
                out.append(working)
                continue
            merged_flags = sorted(set(chunk.quality_flags) | {ATOMIC_SPLIT_QUALITY_FLAG})
            cursor = chunk.start_index
            for piece_text in self._byte_safe_split(chunk.content, cap):
                piece_chunk = chunk.model_copy(
                    update={
                        "content": piece_text,
                        "start_index": cursor,
                        "end_index": cursor + len(piece_text),
                        "quality_flags": merged_flags,
                    }
                )
                cursor += len(piece_text)
                out.append(_WorkingChunk(chunk=piece_chunk, boundary_changed=True))
        return out

    def _byte_safe_split(self, text: str, max_bytes: int) -> List[str]:
        """Split text into UTF-8 byte-safe pieces, each ≤ max_bytes.

        Tries line boundaries first to keep table rows / equation lines intact;
        falls back to per-codepoint byte-aware accumulation for any line that
        alone exceeds max_bytes. Codepoint-safe: never breaks a multibyte char,
        because we iterate Python str characters (Unicode codepoints) and
        accumulate UTF-8 byte counts.
        """
        pieces: List[str] = []
        buffer = ""
        buffer_bytes = 0
        for line in text.splitlines(keepends=True):
            line_bytes = len(line.encode("utf-8"))
            if line_bytes > max_bytes:
                if buffer:
                    pieces.append(buffer)
                    buffer = ""
                    buffer_bytes = 0
                pieces.extend(self._byte_codepoint_hard_cut(line, max_bytes))
                continue
            if buffer_bytes + line_bytes > max_bytes:
                pieces.append(buffer)
                buffer = line
                buffer_bytes = line_bytes
            else:
                buffer += line
                buffer_bytes += line_bytes
        if buffer:
            pieces.append(buffer)
        return pieces

    def _byte_codepoint_hard_cut(self, text: str, max_bytes: int) -> List[str]:
        """Codepoint-safe byte-bound hard cut.

        Iterates Python str characters (Unicode codepoints), never splitting a
        UTF-8 multibyte sequence in the middle. Each output piece is ≤ max_bytes.
        """
        pieces: List[str] = []
        buffer = ""
        buffer_bytes = 0
        for ch in text:
            ch_bytes = len(ch.encode("utf-8"))
            if buffer_bytes + ch_bytes > max_bytes:
                pieces.append(buffer)
                buffer = ch
                buffer_bytes = ch_bytes
            else:
                buffer += ch
                buffer_bytes += ch_bytes
        if buffer:
            pieces.append(buffer)
        return pieces

    def _finalize(self, workings: List[_WorkingChunk]) -> List[ChunkRecord]:
        finalized: List[ChunkRecord] = []
        for new_index, working in enumerate(workings):
            chunk = working.chunk
            if working.boundary_changed:
                new_chunk_id = f"{chunk.doc_id}:cp{new_index:05d}"
            else:
                new_chunk_id = chunk.chunk_id

            new_source_ref = chunk.source_ref.model_copy(update={"chunk_id": new_chunk_id})
            new_metadata = dict(chunk.metadata)
            new_metadata["chunk_id"] = new_chunk_id
            new_metadata["heading_path"] = list(chunk.heading_path)
            new_metadata["page_start"] = chunk.page_start
            new_metadata["page_end"] = chunk.page_end
            new_metadata["quality_flags"] = list(chunk.quality_flags)
            new_metadata["content_type"] = chunk.content_type
            new_metadata["source_ref"] = new_source_ref.model_dump(mode="json")

            finalized.append(
                chunk.model_copy(
                    update={
                        "chunk_id": new_chunk_id,
                        "chunk_index": new_index,
                        "source_ref": new_source_ref,
                        "metadata": new_metadata,
                    }
                )
            )
        return finalized

    def _build_section_parents(self, chunks: List[ChunkRecord]) -> List[ChunkRecord]:
        """同 heading_path 下连续 ≥2 个文本子块聚合为一个 section parent。"""
        if not chunks:
            return []
        parents: List[ChunkRecord] = []
        group: List[ChunkRecord] = []

        def flush():
            if len(group) >= 2:
                parents.append(self._build_one_parent(group, parent_seq=len(parents)))
            group.clear()

        for chunk in chunks:
            if chunk.content_type not in TEXT_CONTENT_TYPES:
                flush()
                continue
            if not chunk.heading_path:
                flush()
                continue
            if not group or list(group[-1].heading_path) == list(chunk.heading_path):
                group.append(chunk)
            else:
                flush()
                group.append(chunk)
        flush()
        return parents

    def _build_one_parent(self, group: List[ChunkRecord], parent_seq: int) -> ChunkRecord:
        first = group[0]
        content = MERGE_SEPARATOR.join(c.content for c in group)
        page_starts = [c.page_start for c in group if c.page_start is not None]
        page_ends = [c.page_end for c in group if c.page_end is not None]
        quality_flags: set[str] = set()
        for c in group:
            quality_flags.update(c.quality_flags)
        parent_chunk_id = f"{first.doc_id}:parent:{parent_seq:05d}"
        source_ref = first.source_ref.model_copy(
            update={
                "chunk_id": parent_chunk_id,
                "content_type": SECTION_PARENT_CONTENT_TYPE,
                "page_start": min(page_starts) if page_starts else None,
                "page_end": max(page_ends) if page_ends else None,
            }
        )
        metadata = {
            "kb_id": first.kb_id,
            "doc_id": first.doc_id,
            "chunk_id": parent_chunk_id,
            "content_type": SECTION_PARENT_CONTENT_TYPE,
            "heading_path": list(first.heading_path),
            "page_start": source_ref.page_start,
            "page_end": source_ref.page_end,
            "quality_flags": sorted(quality_flags),
            "source_ref": source_ref.model_dump(mode="json"),
            "chunk_role": "parent",
            "child_chunk_ids": [c.chunk_id for c in group],
        }
        if "_source" in first.metadata:
            metadata["_source"] = first.metadata["_source"]
        if "_file_name" in first.metadata:
            metadata["_file_name"] = first.metadata["_file_name"]
        if "_extension" in first.metadata:
            metadata["_extension"] = first.metadata["_extension"]
        if "parser_engine" in first.metadata:
            metadata["parser_engine"] = first.metadata["parser_engine"]
        return ChunkRecord(
            chunk_id=parent_chunk_id,
            doc_id=first.doc_id,
            kb_id=first.kb_id,
            content=content,
            chunk_index=parent_seq,
            start_index=first.start_index,
            end_index=group[-1].end_index,
            heading_path=list(first.heading_path),
            page_start=source_ref.page_start,
            page_end=source_ref.page_end,
            content_type=SECTION_PARENT_CONTENT_TYPE,
            source_ref=source_ref,
            quality_flags=sorted(quality_flags),
            metadata=metadata,
            parent_chunk_id=None,
        )

    def _link_children_to_parents(
        self,
        chunks: List[ChunkRecord],
        parents: List[ChunkRecord],
    ) -> List[ChunkRecord]:
        child_to_parent: dict[str, str] = {}
        for parent in parents:
            for child_id in parent.metadata.get("child_chunk_ids", []):
                child_to_parent[child_id] = parent.chunk_id
        if not child_to_parent:
            return chunks
        linked: List[ChunkRecord] = []
        for chunk in chunks:
            parent_id = child_to_parent.get(chunk.chunk_id)
            if parent_id is None:
                linked.append(chunk)
                continue
            new_metadata = dict(chunk.metadata)
            new_metadata["parent_chunk_id"] = parent_id
            linked.append(
                chunk.model_copy(
                    update={
                        "parent_chunk_id": parent_id,
                        "metadata": new_metadata,
                    }
                )
            )
        return linked


chunk_policy_service = ChunkPolicyService()
