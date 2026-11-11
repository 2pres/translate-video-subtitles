# Translate Video Subtitles

基于 starinzlob/translate-video-subtitles 的字幕 Skill，新增正式合成前的生图样式预览与用户确认流程。

## 工作流

1. 检查视频并抽取真实画面，试译代表性对白。
2. 使用图像生成工具制作字体、字号和位置样稿。
3. 用户确认后，用实际字幕引擎核对排版。
4. 完成全片翻译、字幕合成和验收，保留 SRT/ASS。

生图用于样式示意；实际字体度量、换行和时间轴仍以字幕渲染引擎为准。

## 安装

将 `skills/translate-video-subtitles` 放到 Agent 的 skills 目录。详细依赖与流程见 `SKILL.md`。

## 来源

上游：https://github.com/starinzlob/translate-video-subtitles （MIT）。本仓库保留上游署名及许可。
