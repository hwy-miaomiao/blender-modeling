# -*- coding: utf-8 -*-
"""templates/edit_model_template.py（模式 B）的静态回归测试。

CI 环境没有 Blender，模板首行 import bpy 无法直接 import，因此这里只做源码级
契约断言；真正的 Blender 4.0.2 E2E 证据记录在 .audit/round7/fixes/r7-bl-tools.md。

覆盖两条真实修复（修复前均真机复现过失败）：
- R1：模式 B 的 material 编辑必须用 kit 的 update_existing=True + all_slots=True，
  否则源文件已有同名材质时参数不更新、多槽对象只换槽 0，导出 glb 静默保留原材质。
- R2：源 .blend 损坏时 open_blend 返回 {}，模板必须明确报错退出（exit 1），
  不能继续用空 info 取 object_count 而 KeyError 崩溃。
"""
import ast
import os
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "templates", "edit_model_template.py")


class EditModelTemplateContractTests(unittest.TestCase):
    def setUp(self):
        with open(TEMPLATE, encoding="utf-8") as fh:
            self.text = fh.read()

    def test_parser_accepts_template(self):
        ast.parse(self.text)  # 语法错误会在这里直接失败

    def test_material_edit_updates_existing_and_all_slots(self):
        # R1 回归：删掉任一参数都会让模式 B 的材质编辑重新变成静默无效
        self.assertIn("update_existing=True", self.text)
        self.assertIn("all_slots=True", self.text)
        # 不允许退回「同名复用不改参数 + 只换槽 0」的旧写法
        self.assertNotIn("assign(ob, mat(m_name))", self.text)

    def test_corrupt_blend_has_explicit_guard(self):
        # R2 回归：open_blend 失败返回 {}，必须有明确错误分支并 exit 1
        self.assertIn("if not info:", self.text)
        self.assertIn("无法打开 .blend", self.text)
        self.assertIn("sys.exit(1)", self.text)

    def test_missing_blend_errors(self):
        self.assertIn("缺少 --blend", self.text)
        self.assertIn("找不到 .blend 文件", self.text)

    def test_export_stem_contract(self):
        # 模式 B 默认产物名是 model-edited.*，check_output 依据 report.json exports 定位
        self.assertIn('EXPORT_STEM = "model-edited"', self.text)


if __name__ == "__main__":
    unittest.main()
