# 尚未實作的履歷編輯欄位／操作：Agent 主線待辦

> 盤點日期：2026-11-21；來源為本 Repository 的 104 source-mapped writers、既有真實 104 GET 的**欄位名稱**，以及 [104 editor coverage](tw104-editor-coverage.md)。這是**已知缺口**，不保證涵蓋新版網站所有 UI 控制。
>
> **定義：** 此清單只列**缺少可執行的安全寫入功能／特定未支援的欄位變更模式**。已經有 SDK writer、但只經過合成測試或尚未經過真實 104 測試的欄位，一律**不列入**。只會讀取、離線規劃請求，**不等於有實際寫入實作**。
>
> **進度標準：** 新增「真實可用欄位覆蓋率」必須在使用者授權的真實 104 網站，完成適用的 CREATE／READ／UPDATE／READ／DELETE／READ，獨立 GET 確認且**精確還原原狀**。對只適用 UPDATE 的欄位，要求修改／讀回／還原，不可硬湊 CRUD。**本地測試數量、GitHub CI、原始碼觀察、合成 Mock、離線計畫都不算此項進度。**

## 本輪起點與跳過範圍（使用者指定，2026-11-21）

**從 P0-07 開始，依序往 P0-08、P0-09 ……前進。P0-01～P0-06 暫不處理。**
這是優先順序調整，不表示前六項已完成，也不得擅自回去實作。

**目前 P0-07 狀態：已新增可執行的 browser-only SDK／CLI／HTTP
證照關聯／單筆解除 writer，但真實 104 網站驗證仍阻塞。**
官方 Vuex action `form/certificate/setCertificationConnect`、
`deleteCertificationConnect` 可免去猜測 API URL；寫入前會檢查目前
網頁選取履歷及帳號既有證照清單，寫入後 GET 驗證分組
`certifications[].items[].id`、其餘證照 metadata 與其他履歷區塊。
**仍未通過真實 CRUD。** 2026-11-21 改用代理 #1 後登入成功，
104 真實測試履歷 GET 成功；但該履歷 `certificate.formData` 是空的，
查到的 `/profile/`、`/profile/set/` 頁面沒有載入預期的 Vuex store；
`/profile/intro` 轉到 `/resumes/`，那是公開履歷範本，不是個人編輯器。
已從官方編譯前端找到真正的個人編輯路徑
`/profile/edit?vno=<VERSION_NO>`；使用私人測試履歷的版本成功得到
HTTP 200 並載入編輯器 JS，但保存的登入狀態下**沒有掛載證照 UI／
可用 Vuex store**。其後再試代理 #1 的全新登入回報
`AuthenticationRequired`。此後**也已測試 curl_cffi 混合傳輸**：
代理 #1 的同 Session 瀏覽器真實 GET 成功，但 `curl_cffi
chrome146` 的 Overview GET 為 HTTP 403；改 `chrome150` 仍是 403，
另一次瀏覽器入口自身也得到 403。Cloudflare 僅見 edge headers，
不是已確認的 challenge；不能斷言一定是 TLS 指紋或密碼問題。
**尚未執行任何證照關聯寫入、解除或還原；真實覆蓋率增量 0。**
下一步定位真正可操作的編輯器／HTTP 證照關聯、帳號可連結證照與
穩定原生 Session，完成 P0-07 寫入／獨立讀回／還原後才開始 P0-08。
P0-08 的外語證照關聯依賴此項契約；不可把 P0-07 的本地測試當作
已完成的網站支援。

## A. 104：仍未實作的欄位缺口

> **P0-07 已從「沒有實作」移至前述「已實作、待真實驗證」狀態。**
> 按使用者指令，依然先處理 P0-07 的真實網站驗證與阻礙；
> 如需繼續新增 writer，下一個尚未實作 ID 是 P0-08。

| ID | 尚缺的原生欄位／能力 | 現有證據、實作缺口與交付目標 |
|---|---|---|
| **P0-01** | `info.formData.info.jobStatus` 求職狀態 | 真實 GET 有此鍵；`INFO_PATHS` 無此欄位。先確認其編輯 UI 是帳號層級或履歷層級，再建立完整可回復的合法 writer。 |
| **P0-02** | `info.formData.info.birthYear`、`birthMonth`、`birthDate` 出生日期 | 真實 GET 有這三鍵；INFO writer 明確排除。須確認日期欄位同步／權限／真實請求，不可猜測或不完整覆寫。 |
| **P0-03** | `info.formData.info.cellphone` 帳號相關手機 | 真實 GET 有鍵但沒有寫入路徑；可能涉及 OTP／帳號設定。先確定允許的修改程序；不得繞過驗證。 |
| **P0-04** | `info.formData.info.showPersonalLink` 個人連結顯示控制 | 真實 GET 有此鍵、`INFO_PATHS` 沒有；既有 `personalLink1..3{Type,Url}` 已實作，不可重做。先確認這個開關是否為實際可編輯 UI。 |
| **P0-05** | `info.formData.themeChoose.backgroundColor` 背景色 | INFO serializer 已讀取、保留此值；無單獨寫入欄位路徑。`set_theme` 已能改 theme ID，**不等於**能編輯背景色。需映射顏色選擇與保存條件。 |
| **P0-06** | `info.formData.info.personalCover`、`personalHeadshotFileId`、`personalImageUrl` 封面／頭像與可能相關的 `delAvatar` | 已觀察到 GET／頂層鍵，但尚無完整頭像／封面上傳、替換、清除的 writer。先區分唯讀顯示 URL、檔案 ID 與真正可修改控制，再補媒體生命週期。 |
| **P0-08** | `language.formData.languages.foreign[].certificate` 外語證照關聯 | FOREIGN 原生紀錄 CRUD **已實作**，但存在關聯時 SDK 拒絕更新；沒有關聯建立／解除 writer。需與 P0-07 一起確認關聯身分與完整保存語意。 |
| **P0-09** | `project.formData.projects[].img` 及 PROJECT 圖片／影片 | 無媒體 PROJECT CRUD **已實作**。尚缺既有媒體紀錄的安全變更，以及圖片／影片上傳、替換、刪除／還原。禁止讓無媒體 serializer 清空附件。 |
| **P0-10** | CUSTOM `IMAGE=4`／`MAGAZINE=5` 可持久化內容 | `custom_themes.py` 有離線 encoder；IMAGE 曾有 raw native 測試，但**沒有 SDK／CLI／HTTP CRUD writer**；MAGAZINE raw POST 未成功。需確認 2 個內容位置與媒體生命週期，實作原生 CRUD、GET 比對與還原。 |
| **P0-11** | CUSTOM `CLASSIC=1`／`BANNER=2` 的媒體欄位、跨版型轉換 | 單筆無媒體 CLASSIC／BANNER CRUD **已實作**，TEXT 亦已實作；但非 `type:0` 媒體及已有 CUSTOM 的 theme 轉換**沒有** writer。只補缺少的行為，不重做既有 TEXT／no-media CRUD。 |
| **P0-12** | `portfolio.formData.portfolios[]` **既有** LINK 名稱／URL 修改、FILE 更換／重新命名 | `mutate_portfolio()` 只有 LINK CREATE／單筆 DELETE；FILE 上傳與 DELETE 另有實作。沒有現有項目的 UPDATE／安全替換路徑。需保留其他附件與順序，不得用無法確認的刪除重建冒充 UPDATE。 |
| **P0-13** | PORTFOLIO 暫存上傳檔清理、必要的轉檔取消／產物替換 | `request_portfolio_conversion()` 已能發出轉檔請求，`get_portfolio_conversion_status()` 已能查詢狀態；**只有**暫存檔清理／取消／替換的完整可控生命週期尚無 writer。勿列已實作的轉檔與查詢為缺失。 |

## B. 104：特定寫入分支與操作仍缺實作

| ID | 未支援的變更模式 | 實作與驗證邊界 |
|---|---|---|
| **P1-01** | LANGUAGE `local[].type`／`foreign[].type` **變更既有語言類型** | 既有 CRUD／非 type 的 UPDATE 已存在；UI 可能要先 CREATE 新類型、再 DELETE 舊類型，SDK 目前刻意拒絕。補安全複合流程，**不是**重新做 FOREIGN CREATE／DELETE。 |
| **P1-02** | EXPERIENCE 新增時 `companyVisibility=False` | 現有 CREATE 已實作，但真實網站曾把 false 改存 true，SDK 因而拒絕此值。需弄清 UI「隱藏公司」實際保存規則，不可把錯存當成功。 |
| **P1-03** | REFERRER 額外的條件式聯絡資訊可見度（如官方 UI 確實可編輯） | `name/company/position/email/tel` 已有 CRUD。其他欄位需先確認實際 UI 和鍵名，不能憑猜測發明 JSON。 |
| **P1-04** | 非相鄰 SKILL／EDUCATION 等紀錄移動，3 筆以上 REFERRER 排序 | `sort_records()` 已支援部分排序，PORTFOLIO 部分非相鄰 move 也有實測；只補**未實作的排列方式**，要驗證 move 與 swap 語意。 |
| **P1-05** | SIDEBAR 顯示／隱藏／額外 metadata 控制（**僅在確實是可編輯 UI 時**） | 完整清單重新排序已實作。GET 的完成度資訊可能是唯讀衍生值，不能為湊覆蓋率臆造 writer。 |
| **P1-06** | 整份履歷 **重新命名** | `list_resumes()`、`get_resume()`、`create_resume()` 已實作；前端找到 `renameResume` 動作名稱，但沒有可確認的寫入本文／讀回格式，也沒有 `rename_resume()`。 |
| **P1-07** | 整份履歷 **刪除／複製**（以官方 UI 有此權限為前提） | 單欄 CRUD 不等於整份履歷 CRUD；目前無 `delete_resume()`、`duplicate_resume()`。絕對不能對主要測試履歷做不可還原的刪除。 |

## C. 其他平台：整個 Provider 仍無實作

- **Cake：** `providers/cake` 只有 placeholder；沒有完整的登入／履歷列舉／讀取／建立／欄位修改／儲存 writer。
- **Yourator：** `providers/yourator` 只有 placeholder，情況相同。
- **Greenhouse：** `providers/greenhouse` 只有 placeholder；先確認求職者端與雇主招聘 API 的權限邊界，再盤點真實可編輯欄位。

這三個 Provider 的**欄位級**清單必須從實際官方 UI／API 契約取得，不得虛構欄位。建立抽象介面本身不算新增可編輯欄位。

## D. 明確排除：已有實作，只有真實網站驗證尚未完成

- **FOREIGN LANGUAGE CREATE／DELETE：** 既有 SDK 原生 POST／DELETE 已實作；尚缺「唯一未占用 type」在真實 104 的完整 CRUD、獨立 GET 與還原。屬**待真實驗證**，不能重新列成「未實作」。
- **P0-07 CERTIFICATE association browser-only connect/disconnect：** 已有官方 Vuex dispatch writer；尚未通過真實站點驗證，不能當作完整網站 CRUD 支援。
- **CUSTOM CLASSIC／BANNER 無媒體 CRUD、TEXT CRUD、UNDER18 POST／PUT：** 已有 SDK writer；其中部分仍只有合成測試。不能重做來充當實作新進度。
- **PROJECT 無媒體 CRUD、PORTFOLIO LINK CREATE／DELETE、FILE 上傳／DELETE、轉檔請求／狀態查詢、BIO、CERTIFICATE 文字、INFO 已映射欄位、各類既有 record CRUD／排序：** 有實際程式路徑；真實驗證證據另見 [104 editor coverage](tw104-editor-coverage.md)。
- `info.formData.info.age`、簽名附件 URL、履歷完成度等可能是**唯讀／衍生**值，不能直接算成「未實作的可編輯欄位」。

## E. Agent 強制工作與交接規則

1. 每輪開工先寫出 **正在處理的 ID**（使用者目前指定 P0-07）及缺少的特定欄位／操作。除非使用者改變目標，**不得擅自換題**。
2. 先找該 ID 所需**官方請求與讀回證據**。遇到登入或端點阻礙，調查此阻礙而不是改做框架、CI、批次、冪等、預檢或其他已實作欄位。
3. 實作目標是**可執行的 SDK writer**，依需求附 CLI／HTTP 薄包裝，包含寫入前驗證、原生寫入、獨立讀回、還原策略；合成測試是必要品質檢查，**不是覆蓋率進度**。
4. **只在真實 104 網站完成適用 CRUD／獨立 GET／精確還原後，才報告真實覆蓋率增加。** 若被阻塞，明記「本輪新增真實驗證欄位：0」與具體原因，不把本地 CI 通過當作成果。
5. 實作完成但網站尚未驗證的功能，從「無 writer」移到另外的**待真實驗證**追蹤；進度仍為 0，不能偷偷從待辦消失。只允許改動本 ID 與直接必要的基礎修正，提交 PR 後下一輪沿用 ID，不重新盤點整個環境。
6. 私人履歷、帳密、Cookies、代理、GET 值、備份與測試紀錄**不得提交到公開 Repo**。未經授權不編輯其他履歷、全域帳號憑證或不可還原的資料。
