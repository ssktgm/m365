# HTTP POST ツール（Python デスクトップ版）

HTML 版と同等の機能を Python 標準ライブラリ（`tkinter` + `urllib.request`）のみで実装したデスクトップアプリです。HTML 版の [sample-config.json](../sample-config.json) などと設定 JSON フォーマットを共有できます。

- **実行モード**（初期表示）: 送信先 URL の確認と、定義済み変数のセット・POST 送信のみを行うシンプルな画面です（JSON ファイル読込のみ利用可）。
- **設定モード**: エンドポイント URL・変数定義・ヘッダー・ペイロードの編集とプレビュー、設定の保存／読込／エクスポート／リセットが行えます。

## 主なファイル

- `http_post_tool.py` - アプリ本体
- `build_mac.sh` - macOS 用 `.app` ビルドスクリプト
- `build_win.bat` - Windows 用 `.exe` ビルドスクリプト
- `../.github/workflows/build.yml` - macOS / Windows 両方を自動ビルドする GitHub Actions ワークフロー

## Python から直接実行する方法

```bash
python3 python_tool/http_post_tool.py
```

## macOS 用 `.app` のビルド・起動

```bash
bash python_tool/build_mac.sh
```

ビルドすると `python_tool/dist/HttpPostTool.app` が生成されます。Finder でダブルクリックするか、以下で起動できます。

```bash
open python_tool/dist/HttpPostTool.app
```

> **Note**: 未署名のローカルビルドであるため、別の Mac 等へ配布して初回起動する際は右クリック →「開く」が必要になる場合があります。

## Windows 用 `.exe` のビルド

macOS 上では Windows 用 `.exe` を直接クロスコンパイルできないため、次のいずれかの方法でビルドしてください。

### 方法1: Windows PC でビルドする

Windows 環境で Python（3.10 以上推奨）と `pyinstaller`（必要に応じて `certifi`）を用意し、`build_win.bat` を実行します。

```bat
pip install pyinstaller certifi
cd python_tool
build_win.bat
```

成功すると `python_tool\dist\HttpPostTool.exe` が生成されます。

### 方法2: GitHub Actions で自動ビルドする（Windows 端末不要）

リポジトリを GitHub へ push するか、Actions タブから **Build Desktop Apps**（`.github/workflows/build.yml`）を手動実行（`workflow_dispatch`）すると、`HttpPostTool-macOS` と `HttpPostTool-Windows`（`HttpPostTool.exe`）のアーティファクトが生成されます。

#### GitHub Releases への自動公開（ログイン不要・期限なしで配布する場合）

タグを push すると、ビルド完了後にリポジトリの **Releases** ページへ `HttpPostTool.exe` と `HttpPostTool-macOS.zip` が自動添付されます。

```bash
git tag v1.0.0
git push origin v1.0.0
```
