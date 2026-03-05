import glob
import os
import re

import maya.cmds as cmds
from arnold import (
    AI_CACHE_ALL,
    AI_NODE_SHADER,
    AI_NODE_SHAPE,
    AiBegin,
    AiEnd,
    AiNodeGetStr,
    AiNodeIs,
    AiNodeIteratorFinished,
    AiNodeIteratorGetNext,
    AiSceneLoad,
    AiUniverse,
    AiUniverseCacheFlush,
    AiUniverseGetNodeIterator,
)

_FRAME_RE = re.compile(r'#+')


def _resolve_dso_paths(dso: str) -> list[str]:
    """DSOパスのフレームパターン(####)を展開して正規化されたパスのリストを返す。"""
    if _FRAME_RE.search(dso):
        pattern = _FRAME_RE.sub(lambda m: '[0-9]' * len(m.group(0)), dso)
        return [os.path.normpath(p) for p in glob.glob(pattern)]
    return [os.path.normpath(dso)]


def collect_standin_dsos() -> set[str]:
    """シーン内のaiStandInノードからDSOファイルパスを収集する。"""
    standin_dsos = set()
    for standin in cmds.ls(type='aiStandIn', long=True) or []:
        dso = cmds.getAttr(f'{standin}.dso')
        if not dso or dso.lower().endswith('.abc'):
            continue
        standin_dsos.update(_resolve_dso_paths(dso))
    return standin_dsos


def extract_image_files(standin_dsos: set[str], report) -> tuple[set[str], set[str]]:
    """Arnold APIでDSOファイルを再帰的に読み込み、imageノードのテクスチャパスを抽出する。

    Returns:
        tuple[set[str], set[str]]: (テクスチャパス, 全DSOパス)
    """
    imagefiles = set()
    queue = list(standin_dsos)
    visited = set(standin_dsos)
    processed = 0

    report(f"Processing {len(queue)} Arnold procedural dependencies...")

    try:
        AiBegin()
        universe = AiUniverse()
        while queue:
            dso = queue.pop()
            if not AiSceneLoad(universe, dso, None):
                cmds.warning(f'Failed to load procedural: {dso}')
                continue

            node_iter = AiUniverseGetNodeIterator(universe, AI_NODE_SHADER | AI_NODE_SHAPE)
            while not AiNodeIteratorFinished(node_iter):
                node = AiNodeIteratorGetNext(node_iter)
                if AiNodeIs(node, 'image'):
                    imagefile = AiNodeGetStr(node, 'filename')
                    if imagefile:
                        imagefiles.add(str(imagefile))
                elif AiNodeIs(node, 'procedural'):
                    nested_dso = AiNodeGetStr(node, 'filename')
                    if nested_dso:
                        nested_dso = str(nested_dso)
                        if nested_dso.lower().endswith('.abc'):
                            continue
                        for normalized in _resolve_dso_paths(nested_dso):
                            if normalized not in visited:
                                visited.add(normalized)
                                queue.append(normalized)

            AiUniverseCacheFlush(universe, AI_CACHE_ALL)

            processed += 1
            if processed % 100 == 0:
                report(f"Processed {processed}/{len(visited)} Arnold procedural files...")
    except Exception as e:
        cmds.warning(f'Failed to load procedural: {e}')
    finally:
        AiEnd()

    report(f"Processed {processed} Arnold procedural files (found {len(imagefiles)} textures)")
    return imagefiles, visited