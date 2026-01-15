# 如何將監控程式部署到 GitHub (每天自動更新)

這個指南將教您如何將程式上傳到 GitHub，讓它每天自動幫您抓資料，並且產生網頁報告。

## 步驟 1: 準備 GitHub 帳號
1. 如果您還沒有帳號，請至 [github.com](https://github.com/) 註冊一個免費帳號。
2. 登入後，點擊右上角的 "+"號 -> **New repository**。
3. **Repository name** 輸入 `etf-monitor` (或您喜歡的名字)。
4. 選擇 **Public** (公開) 或 **Private** (私有)。
   - *注意：若設為 Private，GitHub Pages 免費版可能有限制，但 GitHub Actions 仍可運作。建議先設為 Public 測試。*
5. 點擊 **Create repository**。

## 步驟 2: 上傳檔案
您有兩種方式上傳檔案：

### 方法 A: 使用網頁介面 (最簡單)
1. 在您剛建立的 GitHub 頁面中，點擊 **uploading an existing file**。
2. 將 `Web_Deployment` 資料夾內的所有檔案 (包含 `.github` 資料夾) 拖曳到上傳區。
   - **重要**：請確保 `.github/workflows/daily_monitor.yml` 這個路徑結構是正確的。如果網頁介面不好上傳資料夾，請使用 GitHub Desktop 或 Git 工具。

### 方法 B: 使用 Git 指令 (推薦)
1. 安裝 Git。
2. 在 `ActiveETF_Monitor_for_Web` 資料夾中按右鍵開啟終端機。
3. 執行以下指令：
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/您的帳號/etf-monitor.git
   git push -u origin main
   ```

## 步驟 3: 設定 GitHub Pages (顯示網頁)
1. 進入您的 GitHub Repository 頁面。
2. 點擊上方的 **Settings** 分頁。
3. 在左側選單找到 **Pages** (或 GitHub Pages)。
4. 在 **Build and deployment** 下的 **Source** 選擇 `Deploy from a branch`。
5. 在 **Branch** 選擇 `main`，資料夾選擇 `/ (root)`。
6. 點擊 **Save**。

## 步驟 4: 完成！
*   **自動執行**：每天台灣時間 18:00，GitHub Actions 會自動執行程式抓資料。
*   **查看網頁**：等待幾分鐘後，GitHub Pages 會顯示您的網址 (通常是 `https://您的帳號.github.io/etf-monitor/`)。
*   點擊該網址，就會出現我們設定的 `index.html`，並自動跳轉到最新的報告！
