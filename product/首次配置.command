#!/bin/zsh
set -e

cd "$(dirname "$0")"

echo ""
echo "天策 AI 投研数字员工｜双引擎配置"
echo "--------------------------------"
echo "默认优先使用 Codex 的 ChatGPT 订阅额度。"
echo "OpenAI API Key 是可选备用，不填也能使用 Codex 引擎。"
echo ""

CODEX_BIN=""
if command -v codex >/dev/null 2>&1; then
  CODEX_BIN="$(command -v codex)"
elif [[ -x "/Applications/ChatGPT.app/Contents/Resources/codex" ]]; then
  CODEX_BIN="/Applications/ChatGPT.app/Contents/Resources/codex"
fi

CODEX_READY="no"
if [[ -n "$CODEX_BIN" ]] && "$CODEX_BIN" login status 2>&1 | grep -q "Logged in using ChatGPT"; then
  CODEX_READY="yes"
  echo "✓ Codex 订阅引擎：已检测到 ChatGPT 登录"
else
  echo "△ Codex 订阅引擎：尚未检测到 ChatGPT 登录"
  echo "  请先打开 Codex，使用 ChatGPT 账号登录；登录后无需重新填写 API Key。"
fi
echo ""

EXISTING_KEY=""
if [[ -f .env ]]; then
  EXISTING_KEY="$(grep '^OPENAI_API_KEY=' .env 2>/dev/null | head -n 1 | cut -d= -f2-)"
fi

read "USE_API?是否配置 OpenAI API 备用引擎？（y/N）："
OPENAI_KEY="$EXISTING_KEY"
if [[ "$USE_API" == [yY] ]]; then
  echo "可在 https://platform.openai.com/api-keys 创建 Key。"
  read -s "NEW_KEY?请粘贴 API Key（输入时屏幕不会显示）："
  echo ""
  if [[ -n "$NEW_KEY" && "$NEW_KEY" != sk-* ]]; then
    echo "这个内容看起来不像 OpenAI API Key，未保存。"
    read "REPLY?按回车关闭窗口。"
    exit 1
  fi
  [[ -n "$NEW_KEY" ]] && OPENAI_KEY="$NEW_KEY"
fi

umask 077
{
  printf 'OPENAI_API_KEY=%s\n' "$OPENAI_KEY"
  printf 'OPENAI_MODEL=gpt-5.6\n'
  printf 'AI_RESEARCH_ENGINE=auto\n'
  printf 'CODEX_BIN=%s\n' "$CODEX_BIN"
  printf 'CODEX_MODEL=\n'
  printf 'AI_RESEARCH_HOST=127.0.0.1\n'
  printf 'AI_RESEARCH_PORT=8765\n'
} > .env
chmod 600 .env
API_READY="no"
[[ -n "$OPENAI_KEY" ]] && API_READY="yes"
unset OPENAI_KEY NEW_KEY EXISTING_KEY

echo ""
if [[ "$CODEX_READY" == "yes" ]]; then
  echo "配置完成：默认 Codex 订阅，API 自动备用。"
elif [[ "$API_READY" == "yes" ]]; then
  echo "配置完成：当前可使用 OpenAI API；登录 Codex 后会自动优先使用订阅。"
else
  echo "配置文件已保存，但两个引擎都还不可用。请先登录 Codex 或配置 API Key。"
fi
echo "接下来双击“启动研究台.command”。"
read "REPLY?按回车关闭窗口。"
