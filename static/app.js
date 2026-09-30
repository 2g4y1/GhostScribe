// State
    let currentStatus = "idle";
    let activeMeetingId = null;
    let rawCurrentMarkdown = "";
    let hasSeenWelcomeModal = false;
    let hasApiKeyConfigured = false;
    let currentConfiguredModel = "gemini-flash-latest";
    const API_KEY_MASK = "••••••••••••••••••••••••";

    function syncModelSelect(modelName) {
      if (!modelSelect || !modelName) return;
      let opt = modelSelect.querySelector(`option[value="${modelName}"]`);
      if (!opt) {
        opt = document.createElement("option");
        opt.value = modelName;
        opt.textContent = `${modelName} (Aktuell konfiguriert)`;
        modelSelect.appendChild(opt);
      }
      modelSelect.value = modelName;
    }

    // Attachment Tabs & Quick Actions Elements
    const attTabBoth = document.getElementById("attTabBoth");
    const attTabChat = document.getElementById("attTabChat");
    const attTabImages = document.getElementById("attTabImages");
    const attachmentsGrid = document.getElementById("attachmentsGrid");
    const colChat = document.getElementById("colChat");
    const colImages = document.getElementById("colImages");
    const tabImgCount = document.getElementById("tabImgCount");
    const pasteClipboardTextBtn = document.getElementById("pasteClipboardTextBtn");
    const importTextFileBtn = document.getElementById("importTextFileBtn");

    // DOM Elements
    const statusBadge = document.getElementById("statusBadge");
    const statusText = document.getElementById("statusText");
    const micName = document.getElementById("micName");
    const loopbackName = document.getElementById("loopbackName");
    const micVuFill = document.getElementById("micVuFill");
    const teamsVuFill = document.getElementById("teamsVuFill");
    const timerDisplay = document.getElementById("timerDisplay");
    const meetingTitleInput = document.getElementById("meetingTitleInput");
    const meetingParticipantsInput = document.getElementById("meetingParticipantsInput");
    const meetingTypeSelect = document.getElementById("meetingTypeSelect");
    const cancelRecordBtn = document.getElementById("cancelRecordBtn");
    const recordToggleBtn = document.getElementById("recordToggleBtn");
    const recordBtnText = document.getElementById("recordBtnText");
    const pulseRing = document.getElementById("pulseRing");
    const processingBanner = document.getElementById("processingBanner");
    const processStepText = document.getElementById("processStepText");
    const meetingsList = document.getElementById("meetingsList");
    const meetingCount = document.getElementById("meetingCount");
    const searchInput = document.getElementById("searchInput");
    const clearSearchBtn = document.getElementById("clearSearchBtn");
    const searchMatchBadge = document.getElementById("searchMatchBadge");
    const viewTitle = document.getElementById("viewTitle");
    const viewMeta = document.getElementById("viewMeta");
    const markdownBody = document.getElementById("markdownBody");
    const copyMdBtn = document.getElementById("copyMdBtn");
    const downloadMdBtn = document.getElementById("downloadMdBtn");
    const deleteMeetingBtn = document.getElementById("deleteMeetingBtn");
    const audioPlayerSection = document.getElementById("audioPlayerSection");
    const audioElement = document.getElementById("audioElement");
    const userSpeakerName = document.getElementById("userSpeakerName");
    const settingsUserNameInput = document.getElementById("settingsUserNameInput");

    // Attachment & Chat Elements
    const attachmentsAccordion = document.getElementById("attachmentsAccordion");
    const attachmentsToggle = document.getElementById("attachmentsToggle");
    const attachmentsPanel = document.getElementById("attachmentsPanel");
    const attachmentsCountBadge = document.getElementById("attachmentsCountBadge");
    const chatInput = document.getElementById("chatInput");
    const chatCharCount = document.getElementById("chatCharCount");
    const clearChatBtn = document.getElementById("clearChatBtn");
    const dropZone = document.getElementById("dropZone");
    const fileAttachmentInput = document.getElementById("fileAttachmentInput");
    const thumbnailsContainer = document.getElementById("thumbnailsContainer");
    const toastNotification = document.getElementById("toastNotification");
    const imageLightboxModal = document.getElementById("imageLightboxModal");
    const lightboxImg = document.getElementById("lightboxImg");
    const lightboxCaption = document.getElementById("lightboxCaption");
    const closeLightboxBtn = document.getElementById("closeLightboxBtn");

    let attachedImages = []; // { id, filename, data, size }
    let toastTimer = null;

    // Persist and synchronize user name with dynamic auto-resizing
    function adjustUserSpeakerInputWidth() {
      if (!userSpeakerName) return;
      const text = userSpeakerName.value || userSpeakerName.placeholder || "Ich";
      const dynamicWidth = Math.max(54, Math.min(220, text.length * 8.6 + 18));
      userSpeakerName.style.width = dynamicWidth + "px";
    }

    function syncUserName(val) {
      localStorage.setItem("ghostscribe_user_name", val);
      if (userSpeakerName && userSpeakerName.value !== val) {
        userSpeakerName.value = val;
        adjustUserSpeakerInputWidth();
      }
      if (settingsUserNameInput && settingsUserNameInput.value !== val) {
        settingsUserNameInput.value = val;
      }
    }

    const savedUserName = localStorage.getItem("ghostscribe_user_name") || localStorage.getItem("soundy_user_name") || "";
    if (userSpeakerName) {
      userSpeakerName.value = savedUserName;
      adjustUserSpeakerInputWidth();
      userSpeakerName.addEventListener("input", (e) => {
        adjustUserSpeakerInputWidth();
        syncUserName(e.target.value);
      });
    }
    if (settingsUserNameInput) {
      settingsUserNameInput.value = savedUserName;
      settingsUserNameInput.addEventListener("input", (e) => syncUserName(e.target.value));
    }

    // Modal Elements
    const settingsBtn = document.getElementById("settingsBtn");
    const settingsModal = document.getElementById("settingsModal");
    const closeSettingsBtn = document.getElementById("closeSettingsBtn");
    const closeSettingsX = document.getElementById("closeSettingsX");
    const saveSettingsBtn = document.getElementById("saveSettingsBtn");
    const apiKeyInput = document.getElementById("apiKeyInput");
    const modelSelect = document.getElementById("modelSelect");
    const welcomeBanner = document.getElementById("welcomeBanner");

    // Button Flash Helper (Prevents any layout shift / width changes)
    function flashButton(btn) {
      if (!btn) return;
      btn.classList.add("btn-flash-success");
      setTimeout(() => {
        btn.classList.remove("btn-flash-success");
      }, 1200);
    }

    const apiKeyDot = document.getElementById("apiKeyDot");
    const apiKeyHint = document.getElementById("apiKeyHint");
    const defaultAiActSelect = document.getElementById("defaultAiActSelect");

    // EU AI Act Mode Elements
    const aiActModeToggle = document.getElementById("aiActModeToggle");
    const aiActToggleContainer = document.getElementById("aiActToggleContainer");
    const aiActModeTitle = document.getElementById("aiActModeTitle");
    const aiActModeDesc = document.getElementById("aiActModeDesc");

    // Sentiment Warning Confirmation Modal Elements
    const sentimentConfirmModal = document.getElementById("sentimentConfirmModal");
    const confirmSentimentBtn = document.getElementById("confirmSentimentBtn");
    const cancelSentimentBtn = document.getElementById("cancelSentimentBtn");
    const closeSentimentModalX = document.getElementById("closeSentimentModalX");
    let pendingAiActSource = null;

    function updateAiActToggleUI() {
      if (!aiActModeToggle || !aiActToggleContainer) return;
      const isAiAct = aiActModeToggle.checked;
      if (isAiAct) {
        aiActToggleContainer.classList.remove("mode-sentiment");
        if (aiActModeTitle) aiActModeTitle.innerHTML = "🛡️ EU AI Act Modus: Aktiv (Standard)";
        if (aiActModeDesc) aiActModeDesc.innerText = "Sachlich, neutral & rechtssicher – keine Emotions- oder Stimmungsanalyse am Arbeitsplatz.";
        aiActToggleContainer.title = "Klicken zum Umschalten: Gemäß EU AI Act (Art. 5 KI-VO) verzichtet dieser Modus auf jegliche Emotions- und Stimmungsanalyse am Arbeitsplatz.";
      } else {
        aiActToggleContainer.classList.add("mode-sentiment");
        if (aiActModeTitle) aiActModeTitle.innerHTML = "⚠️ Stimmungsanalyse: Aktiv (EU AI Act deaktiviert)";
        if (aiActModeDesc) aiActModeDesc.innerText = "Erfasst Emotionen & Frustration. Gemäß Art. 5 KI-VO am Arbeitsplatz unzulässig!";
        aiActToggleContainer.title = "Klicken zum Reaktivieren des rechtssicheren EU AI Act Modus.";
      }
    }

    function openSentimentWarning(source = "toggle") {
      pendingAiActSource = source;
      if (sentimentConfirmModal) {
        sentimentConfirmModal.classList.add("active");
      }
    }

    function closeSentimentWarning(confirmed = false) {
      if (sentimentConfirmModal) {
        sentimentConfirmModal.classList.remove("active");
      }
      if (confirmed) {
        if (aiActModeToggle) aiActModeToggle.checked = false;
        if (defaultAiActSelect) defaultAiActSelect.value = "false";
        updateAiActToggleUI();
      } else {
        // Revert to true / safe compliant mode
        if (pendingAiActSource === "toggle" || pendingAiActSource === null) {
          if (aiActModeToggle) aiActModeToggle.checked = true;
          updateAiActToggleUI();
        } else if (pendingAiActSource === "settings") {
          if (defaultAiActSelect) defaultAiActSelect.value = "true";
        }
      }
      pendingAiActSource = null;
    }

    if (confirmSentimentBtn) {
      confirmSentimentBtn.addEventListener("click", () => closeSentimentWarning(true));
    }
    if (cancelSentimentBtn) {
      cancelSentimentBtn.addEventListener("click", () => closeSentimentWarning(false));
    }
    if (closeSentimentModalX) {
      closeSentimentModalX.addEventListener("click", () => closeSentimentWarning(false));
    }
    if (sentimentConfirmModal) {
      sentimentConfirmModal.addEventListener("click", (e) => {
        if (e.target === sentimentConfirmModal) closeSentimentWarning(false);
      });
    }

    // Toggle click interception with confirmation
    if (aiActToggleContainer && aiActModeToggle) {
      aiActToggleContainer.addEventListener("click", (e) => {
        e.preventDefault();
        if (aiActModeToggle.checked) {
          // Trying to activate sentiment analysis -> require confirmation!
          openSentimentWarning("toggle");
        } else {
          // Returning to compliant mode -> instant switch
          aiActModeToggle.checked = true;
          if (defaultAiActSelect) defaultAiActSelect.value = "true";
          updateAiActToggleUI();
        }
      });
    }

    if (defaultAiActSelect) {
      defaultAiActSelect.addEventListener("change", () => {
        if (defaultAiActSelect.value === "false") {
          openSentimentWarning("settings");
        } else {
          if (aiActModeToggle) aiActModeToggle.checked = true;
          updateAiActToggleUI();
        }
      });
    }

    // Settings Modal handlers
    function updateSettingsModalUI() {
      if (defaultAiActSelect && aiActModeToggle) {
        defaultAiActSelect.value = aiActModeToggle.checked ? "true" : "false";
      }
      syncModelSelect(currentConfiguredModel);

      if (hasApiKeyConfigured) {
        if (welcomeBanner) welcomeBanner.style.display = "none";
        if (apiKeyDot) {
          apiKeyDot.className = "status-dot-mini green";
          apiKeyDot.title = "Gespeichert & Aktiv";
        }
        apiKeyInput.value = API_KEY_MASK;
        apiKeyInput.placeholder = "AIzaSy...";
        if (apiKeyHint) {
          apiKeyHint.innerHTML = "✅ Gespeichert &amp; Aktiv in deiner lokalen <code>.env</code> Datei.";
          apiKeyHint.style.color = "var(--emerald)";
        }
      } else {
        if (welcomeBanner) welcomeBanner.style.display = "block";
        if (apiKeyDot) {
          apiKeyDot.className = "status-dot-mini orange";
          apiKeyDot.title = "Kein Key hinterlegt";
        }
        apiKeyInput.value = "";
        apiKeyInput.placeholder = "AIzaSy...";
        if (apiKeyHint) {
          apiKeyHint.innerHTML = "🔒 Wird lokal in deiner <code>.env</code> Datei gespeichert und nie weitergegeben.";
          apiKeyHint.style.color = "var(--text-sub)";
        }
      }
    }

    // Intuitive edit-on-focus for API Key without cluttered extra buttons
    apiKeyInput.addEventListener("focus", () => {
      if (apiKeyInput.value.includes("•")) {
        apiKeyInput.value = "";
        apiKeyInput.placeholder = "Neuen API-Key einfügen...";
      }
    });

    apiKeyInput.addEventListener("blur", () => {
      if (!apiKeyInput.value.trim() && hasApiKeyConfigured) {
        apiKeyInput.value = API_KEY_MASK;
        apiKeyInput.placeholder = "AIzaSy...";
      }
    });

    settingsBtn.addEventListener("click", () => {
      updateSettingsModalUI();
      settingsModal.classList.add("active");
    });
    const closeModal = () => settingsModal.classList.remove("active");
    closeSettingsBtn.addEventListener("click", closeModal);
    if (closeSettingsX) closeSettingsX.addEventListener("click", closeModal);

    window.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (imageLightboxModal && imageLightboxModal.style.display === "flex") {
        closeLightbox();
      }
      if (sentimentConfirmModal && sentimentConfirmModal.classList.contains("active")) {
        closeSentimentWarning(false);
      } else if (settingsModal && settingsModal.classList.contains("active")) {
        closeModal();
      }
    });

    saveSettingsBtn.addEventListener("click", async () => {
      const key = apiKeyInput.value.trim();
      const model = modelSelect.value || currentConfiguredModel;
      const isMaskedOrEmpty = !key || key.includes("•") || key.includes("*");

      if (!hasApiKeyConfigured && isMaskedOrEmpty) {
        showToast("⚠️ Bitte gib einen gültigen Gemini API-Key ein.");
        apiKeyInput.focus();
        return;
      }

      const payload = { 
        model: model,
        default_ai_act_mode: defaultAiActSelect ? defaultAiActSelect.value === "true" : true
      };
      if (!isMaskedOrEmpty) {
        payload.api_key = key;
      }

      const origText = saveSettingsBtn.innerText;
      saveSettingsBtn.disabled = true;
      saveSettingsBtn.innerText = "Speichere...";

      try {
        const res = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          if (!isMaskedOrEmpty) {
            hasApiKeyConfigured = true;
          }
          currentConfiguredModel = model;
          syncModelSelect(model);
          if (welcomeBanner && hasApiKeyConfigured) welcomeBanner.style.display = "none";
          if (defaultAiActSelect && aiActModeToggle) {
            aiActModeToggle.checked = defaultAiActSelect.value === "true";
            updateAiActToggleUI();
          }
          settingsModal.classList.remove("active");
          showToast("✅ Einstellungen gespeichert!");
          pollStatus();
        } else {
          const errData = await res.json().catch(() => ({}));
          showToast("❌ Fehler: " + (errData.detail || "Konnte nicht speichern"));
        }
      } catch (err) {
        showToast("❌ Netzwerkfehler beim Speichern: " + err);
      } finally {
        saveSettingsBtn.disabled = false;
        saveSettingsBtn.innerText = origText;
      }
    });

    // Formatting time
    function formatTime(seconds) {
      const s = Math.floor(seconds);
      const hrs = Math.floor(s / 3600);
      const mins = Math.floor((s % 3600) / 60);
      const secs = s % 60;
      return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }

    // Toast Notification
    function showToast(msg) {
      if (!toastNotification) return;
      toastNotification.innerText = msg;
      toastNotification.classList.add("show");
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        toastNotification.classList.remove("show");
      }, 2600);
    }

    // Attachments Accordion Controls
    function toggleAttachmentsAccordion() {
      if (!attachmentsAccordion) return;
      if (attachmentsAccordion.classList.contains("open")) {
        closeAttachmentsAccordion();
      } else {
        openAttachmentsAccordion();
      }
    }

    function openAttachmentsAccordion() {
      if (!attachmentsAccordion) return;
      attachmentsAccordion.classList.add("open");
      attachmentsPanel.style.display = "block";
      attachmentsToggle.setAttribute("aria-expanded", "true");
    }

    function closeAttachmentsAccordion() {
      if (!attachmentsAccordion) return;
      attachmentsAccordion.classList.remove("open");
      attachmentsPanel.style.display = "none";
      attachmentsToggle.setAttribute("aria-expanded", "false");
    }

    if (attachmentsToggle) {
      attachmentsToggle.addEventListener("click", toggleAttachmentsAccordion);
    }

    function updateAttachmentsBadge() {
      if (!attachmentsCountBadge || !attachmentsAccordion) return;
      const imgCount = attachedImages.length;
      const hasChat = chatInput && chatInput.value.trim().length > 0;

      if (imgCount === 0 && !hasChat) {
        attachmentsCountBadge.style.display = "none";
        attachmentsAccordion.classList.remove("has-content");
      } else {
        attachmentsCountBadge.style.display = "inline-block";
        attachmentsAccordion.classList.add("has-content");
        if (imgCount > 0 && hasChat) {
          attachmentsCountBadge.innerText = `${imgCount} Bild${imgCount > 1 ? "er" : ""} + Chat`;
        } else if (imgCount > 0) {
          attachmentsCountBadge.innerText = `${imgCount} Bild${imgCount > 1 ? "er" : ""}`;
        } else {
          attachmentsCountBadge.innerText = "Chat aktiv";
        }
      }
    }

    function updateChatStats() {
      if (!chatInput || !chatCharCount) return;
      const len = chatInput.value.length;
      chatCharCount.innerText = `${len} Zeichen`;
      if (clearChatBtn) {
        clearChatBtn.style.display = len > 0 ? "inline-block" : "none";
      }
      updateAttachmentsBadge();
    }

    if (chatInput) {
      chatInput.addEventListener("input", updateChatStats);
    }
    if (clearChatBtn) {
      clearChatBtn.addEventListener("click", () => {
        chatInput.value = "";
        updateChatStats();
      });
    }

    // Modern Attachment Drawer Tabs
    function setAttachmentTab(tabName) {
      if (!attachmentsGrid || !colChat || !colImages) return;
      [attTabBoth, attTabChat, attTabImages].forEach(b => {
        if (b) b.classList.remove("active");
      });

      if (tabName === "chat") {
        if (attTabChat) attTabChat.classList.add("active");
        colChat.style.display = "flex";
        colImages.style.display = "none";
        attachmentsGrid.style.gridTemplateColumns = "1fr";
      } else if (tabName === "images") {
        if (attTabImages) attTabImages.classList.add("active");
        colChat.style.display = "none";
        colImages.style.display = "flex";
        attachmentsGrid.style.gridTemplateColumns = "1fr";
      } else {
        if (attTabBoth) attTabBoth.classList.add("active");
        colChat.style.display = "flex";
        colImages.style.display = "flex";
        attachmentsGrid.style.gridTemplateColumns = "";
      }
    }

    if (attTabBoth) attTabBoth.addEventListener("click", () => setAttachmentTab("both"));
    if (attTabChat) attTabChat.addEventListener("click", () => setAttachmentTab("chat"));
    if (attTabImages) attTabImages.addEventListener("click", () => setAttachmentTab("images"));

    // Quick Actions for Chat/Notes
    if (pasteClipboardTextBtn) {
      pasteClipboardTextBtn.addEventListener("click", async () => {
        try {
          const text = await navigator.clipboard.readText();
          if (!text || !text.trim()) {
            showToast("⚠️ Keine Texte in der Zwischenablage");
            return;
          }
          const prefix = (chatInput && chatInput.value.trim()) ? "\n\n" : "";
          if (chatInput) {
            chatInput.value = chatInput.value + prefix + text.trim();
            updateChatStats();
            showToast(`📋 ${text.trim().length} Zeichen eingefügt!`);
          }
        } catch (err) {
          showToast("Tipp: Klicke ins Textfeld und drücke Strg+V");
        }
      });
    }

    if (importTextFileBtn) {
      importTextFileBtn.addEventListener("click", () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".txt,.md,.log,.csv,.json,text/plain";
        input.onchange = (e) => {
          if (e.target.files && e.target.files[0]) {
            handleIncomingFiles(e.target.files);
          }
        };
        input.click();
      });
    }


    function addImageAttachment(file, customName) {
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        const dataUrl = e.target.result;
        const id = "att_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7);
        const sizeKb = Math.round(file.size / 1024);
        const name = customName || file.name || "screenshot.png";
        attachedImages.push({
          id: id,
          filename: name,
          data: dataUrl,
          size: `${sizeKb} KB`
        });
        renderThumbnails();
        updateAttachmentsBadge();
      };
      reader.readAsDataURL(file);
    }

    function renderThumbnails() {
      if (!thumbnailsContainer) return;
      thumbnailsContainer.innerHTML = "";
      if (tabImgCount) {
        tabImgCount.innerText = "0";
        tabImgCount.style.display = "none";
      }
      if (attachedImages.length === 0) {
        thumbnailsContainer.style.display = "none";
        return;
      }
      thumbnailsContainer.style.display = "grid";
      if (tabImgCount) {
        tabImgCount.innerText = attachedImages.length;
        tabImgCount.style.display = attachedImages.length > 0 ? "inline-block" : "none";
      }
      attachedImages.forEach((img, idx) => {
        const card = document.createElement("div");
        card.className = "thumbnail-card";
        card.title = `${img.filename} (${img.size}) - Klicken zum Vergrößern`;
        card.innerHTML = `
          <img src="${img.data}" alt="${img.filename}" class="thumbnail-img" />
          <span class="thumbnail-badge">#${idx + 1}</span>
          <button type="button" class="thumbnail-del" title="Entfernen" onclick="event.stopPropagation(); removeAttachment('${img.id}')">✕</button>
        `;
        card.onclick = () => openLightbox(img.data, `${img.filename} (#${idx + 1}) • ${img.size}`);
        thumbnailsContainer.appendChild(card);
      });
    }

    window.removeAttachment = function(id) {
      attachedImages = attachedImages.filter(item => item.id !== id);
      renderThumbnails();
      updateAttachmentsBadge();
    };

    function clearAttachments() {
      attachedImages = [];
      if (chatInput) chatInput.value = "";
      renderThumbnails();
      updateChatStats();
      updateAttachmentsBadge();
      closeAttachmentsAccordion();
    }

    function openLightbox(src, caption) {
      if (!imageLightboxModal) return;
      lightboxImg.src = src;
      lightboxCaption.innerText = caption || "";
      imageLightboxModal.style.display = "flex";
    }

    function closeLightbox() {
      if (!imageLightboxModal) return;
      imageLightboxModal.style.display = "none";
      lightboxImg.src = "";
    }

    if (closeLightboxBtn) closeLightboxBtn.addEventListener("click", closeLightbox);
    if (imageLightboxModal) {
      imageLightboxModal.addEventListener("click", (e) => {
        if (e.target === imageLightboxModal) closeLightbox();
      });
    }
    // Dropzone handlers
    if (dropZone && fileAttachmentInput) {
      dropZone.addEventListener("click", () => fileAttachmentInput.click());
      
      ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.classList.add("drag-active");
        });
      });

      ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.classList.remove("drag-active");
        });
      });

      dropZone.addEventListener("drop", (e) => {
        if (e.dataTransfer && e.dataTransfer.files) {
          handleIncomingFiles(e.dataTransfer.files);
        }
      });

      fileAttachmentInput.addEventListener("change", (e) => {
        if (e.target.files) {
          handleIncomingFiles(e.target.files);
          fileAttachmentInput.value = "";
        }
      });
    }

    function handleIncomingFiles(files) {
      let imgCount = 0;
      let txtCount = 0;

      Array.from(files).forEach(file => {
        const name = (file.name || "").toLowerCase();
        const isImage = file.type.startsWith("image/") || name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".webp");
        const isText = file.type.startsWith("text/") || name.endsWith(".txt") || name.endsWith(".md") || name.endsWith(".log") || name.endsWith(".csv") || name.endsWith(".json");

        if (isImage) {
          addImageAttachment(file, file.name);
          imgCount++;
        } else if (isText) {
          const reader = new FileReader();
          reader.onload = (e) => {
            const textContent = e.target.result;
            if (textContent && textContent.trim()) {
              const prefix = (chatInput && chatInput.value.trim()) ? "\n\n" : "";
              if (chatInput) {
                chatInput.value = chatInput.value + prefix + `=== [Datei: ${file.name}] ===\n` + textContent.trim() + "\n";
                updateChatStats();
                showToast(`📄 Textdatei "${file.name}" importiert!`);
              }
            }
          };
          reader.readAsText(file, "utf-8");
          txtCount++;
        }
      });

      if (imgCount > 0 || txtCount > 0) {
        openAttachmentsAccordion();
        if (imgCount > 0) {
          showToast(`📸 ${imgCount} Bild${imgCount > 1 ? "er" : ""} hinzugefügt!`);
        }
      }
    }

    // Global Strg+V Paste Handler for Screenshots, Files & Text
    window.addEventListener("paste", (e) => {
      const activeEl = document.activeElement;
      const isInput = activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA" || activeEl.isContentEditable);
      
      // If user is currently typing in an input/textarea, let the browser handle it naturally
      if (isInput) return;

      if (!e.clipboardData) return;

      // 1. Check for files (e.g. copied from Windows Explorer)
      if (e.clipboardData.files && e.clipboardData.files.length > 0) {
        e.preventDefault();
        handleIncomingFiles(e.clipboardData.files);
        return;
      }

      // 2. Check for image items
      const items = e.clipboardData.items || [];
      let foundImage = false;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type && items[i].type.indexOf("image") !== -1) {
          const file = items[i].getAsFile();
          if (file) {
            foundImage = true;
            const now = new Date();
            const timeStr = `${String(now.getHours()).padStart(2, "0")}-${String(now.getMinutes()).padStart(2, "0")}-${String(now.getSeconds()).padStart(2, "0")}`;
            const name = `Screenshot_${timeStr}.png`;
            addImageAttachment(file, name);
          }
        }
      }

      if (foundImage) {
        e.preventDefault();
        openAttachmentsAccordion();
        showToast("📸 Screenshot hinzugefügt (Strg+V)!");
        return;
      }

      // 3. Fallback: check for text in clipboard
      const pastedText = e.clipboardData.getData("text/plain");
      if (pastedText && pastedText.trim().length > 0) {
        e.preventDefault();
        const prefix = (chatInput && chatInput.value.trim()) ? "\n\n" : "";
        if (chatInput) {
          chatInput.value = chatInput.value + prefix + pastedText.trim();
          updateChatStats();
          openAttachmentsAccordion();
          showToast(`📝 ${pastedText.trim().length} Zeichen Text aus Zwischenablage eingefügt!`);
        }
      }
    });

    // Toggle Record
    recordToggleBtn.addEventListener("click", async () => {
      if (currentStatus === "idle") {
        if (!hasApiKeyConfigured) {
          welcomeBanner.style.display = "block";
          settingsModal.classList.add("active");
          apiKeyInput.focus();
          return;
        }
        const title = meetingTitleInput.value.trim();
        const participants = meetingParticipantsInput.value.trim();
        const meetingType = meetingTypeSelect.value;
        const userName = (userSpeakerName ? userSpeakerName.value.trim() : "") || "Ich";
        const isAiAct = aiActModeToggle ? aiActModeToggle.checked : true;
        try {
          const res = await fetch("/api/record/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              title: title,
              participants: participants,
              meeting_type: meetingType,
              user_name: userName,
              ai_act_mode: isAiAct
            })
          });
          if (!res.ok) {
            const err = await res.json();
            alert("Fehler beim Starten: " + (err.detail || "Unbekannt"));
          }
        } catch (e) {
          alert("Netzwerkfehler: " + e);
        }
      } else if (currentStatus === "recording") {
        try {
          const chatText = (chatInput ? chatInput.value : "").trim();
          const imagesPayload = attachedImages.map(img => ({
            filename: img.filename,
            data: img.data
          }));
          const isAiAct = aiActModeToggle ? aiActModeToggle.checked : true;
          const res = await fetch("/api/record/stop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              chat_text: chatText,
              images: imagesPayload,
              ai_act_mode: isAiAct
            })
          });
          if (!res.ok) {
            const err = await res.json();
            alert("Fehler beim Stoppen: " + (err.detail || "Unbekannt"));
          } else {
            clearAttachments();
          }
        } catch (e) {
          alert("Netzwerkfehler: " + e);
        }
      }
    });

    // Cancel Record
    cancelRecordBtn.addEventListener("click", async () => {
      if (confirm("Möchtest du die laufende Aufnahme wirklich abbrechen und verwerfen?")) {
        try {
          const res = await fetch("/api/record/cancel", { method: "POST" });
          if (res.ok) {
            clearAttachments();
            pollStatus();
          }
        } catch (e) {
          alert("Fehler beim Abbrechen: " + e);
        }
      }
    });

    // Smart 1-Click Copy: Formatted Rich HTML (Teams, Outlook, Slack, Word) + Clean Markdown (Notepad, Code)
    copyMdBtn.addEventListener("click", async () => {
      if (!rawCurrentMarkdown) return;
      try {
        const htmlContent = marked.parse(rawCurrentMarkdown);
        const blobHtml = new Blob([htmlContent], { type: "text/html" });
        const blobText = new Blob([rawCurrentMarkdown], { type: "text/plain" });

        if (navigator.clipboard && window.ClipboardItem) {
          await navigator.clipboard.write([
            new ClipboardItem({
              "text/html": blobHtml,
              "text/plain": blobText,
            })
          ]);
        } else {
          await navigator.clipboard.writeText(rawCurrentMarkdown);
        }
        flashButton(copyMdBtn);
        showToast("📋 In Zwischenablage kopiert (perfekt formatiert für Teams & Outlook)");
      } catch (err) {
        try {
          await navigator.clipboard.writeText(rawCurrentMarkdown);
          flashButton(copyMdBtn);
          showToast("📋 Protokoll als Text kopiert");
        } catch (e) {
          showToast("❌ Kopieren fehlgeschlagen");
        }
      }
    });

    // Download Markdown
    downloadMdBtn.addEventListener("click", () => {
      if (rawCurrentMarkdown) {
        const blob = new Blob([rawCurrentMarkdown], { type: "text/markdown;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${activeMeetingId || "meeting"}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    });

    // Load meeting details
    async function loadMeeting(id) {
      try {
        const res = await fetch(`/api/meetings/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        
        activeMeetingId = id;
        rawCurrentMarkdown = data.markdown;
        
        viewTitle.innerText = data.metadata.title || id;
        const date = new Date(data.metadata.created_at).toLocaleString("de-DE");
        const extra = data.metadata.participants ? ` • Teilnehmer: ${data.metadata.participants}` : "";
        const isAiAct = data.metadata.ai_act_mode !== false;
        const modeBadge = isAiAct 
          ? `<span class="badge-tag ai-act" title="Rechtssicher gemäß EU AI Act Art. 5: Keine Emotionsanalyse am Arbeitsplatz">🛡️ EU AI Act konform</span>`
          : `<span class="badge-tag sentiment" title="Erweiterte Analyse inkl. Gruppendynamik und Frustration">🎭 Mit Stimmungsanalyse</span>`;
        viewMeta.innerHTML = `Erstellt am ${date} • Modell: ${data.metadata.model_used}${extra} ${modeBadge}`;
        
        markdownBody.innerHTML = marked.parse(data.markdown);
        applyViewerSearchHighlight(true);
        copyMdBtn.style.display = "flex";
        downloadMdBtn.style.display = "flex";
        deleteMeetingBtn.style.display = "flex";

        if (data.audio_url) {
          audioElement.src = data.audio_url;
          audioPlayerSection.style.display = "flex";
          applyAudioMode(currentAudioMode);
        } else {
          audioPlayerSection.style.display = "none";
        }

        renderMeetingsList();
      } catch (err) {
        console.error("Fehler beim Laden des Meetings:", err);
      }
    }

    // Web Audio Channel Router (Mono / Stereo / Solo)
    let audioCtx = null;
    let sourceNode = null;
    let splitter = null;
    let merger = null;
    let gainLL = null;
    let gainLR = null;
    let gainRL = null;
    let gainRR = null;
    let currentAudioMode = "mono"; // Standard: angenehmer Mono-Mix für beide Ohren

    function initWebAudioRouter() {
      if (audioCtx) return;
      try {
        audioCtx = new window.AudioContext();
        sourceNode = audioCtx.createMediaElementSource(audioElement);
        splitter = audioCtx.createChannelSplitter(2);
        merger = audioCtx.createChannelMerger(2);

        gainLL = audioCtx.createGain();
        gainLR = audioCtx.createGain();
        gainRL = audioCtx.createGain();
        gainRR = audioCtx.createGain();

        sourceNode.connect(splitter);

        splitter.connect(gainLL, 0);
        splitter.connect(gainLR, 0);
        splitter.connect(gainRL, 1);
        splitter.connect(gainRR, 1);

        gainLL.connect(merger, 0, 0);
        gainRL.connect(merger, 0, 0);
        gainLR.connect(merger, 0, 1);
        gainRR.connect(merger, 0, 1);

        merger.connect(audioCtx.destination);
        applyAudioMode(currentAudioMode);
      } catch (err) {
        console.warn("Web Audio Router konnte nicht initialisiert werden:", err);
      }
    }

    function applyAudioMode(mode) {
      currentAudioMode = mode;
      if (!audioCtx || !gainLL) return;
      if (audioCtx.state === "suspended") {
        audioCtx.resume();
      }

      if (mode === "mono") {
        // Beide Tonspuren (Ich + Teams) zentriert auf beiden Ohren
        gainLL.gain.value = 0.8;
        gainLR.gain.value = 0.8;
        gainRL.gain.value = 0.8;
        gainRR.gain.value = 0.8;
      } else if (mode === "stereo") {
        // Original: Links = Ich, Rechts = Teams
        gainLL.gain.value = 1.0;
        gainLR.gain.value = 0.0;
        gainRL.gain.value = 0.0;
        gainRR.gain.value = 1.0;
      } else if (mode === "right") {
        // Nur Teams / Andere auf beiden Ohren
        gainLL.gain.value = 0.0;
        gainLR.gain.value = 0.0;
        gainRL.gain.value = 1.0;
        gainRR.gain.value = 1.0;
      } else if (mode === "left") {
        // Nur eigenes Mikrofon auf beiden Ohren
        gainLL.gain.value = 1.0;
        gainLR.gain.value = 1.0;
        gainRL.gain.value = 0.0;
        gainRR.gain.value = 0.0;
      }

      document.querySelectorAll(".audio-mode-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.mode === mode);
      });
    }

    audioElement.addEventListener("play", () => {
      initWebAudioRouter();
      if (audioCtx && audioCtx.state === "suspended") {
        audioCtx.resume();
      }
    });

    document.querySelectorAll(".audio-mode-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        initWebAudioRouter();
        applyAudioMode(btn.dataset.mode);
      });
    });

    // Delete Meeting button handler
    deleteMeetingBtn.addEventListener("click", () => {
      if (activeMeetingId) {
        deleteMeetingPrompt(activeMeetingId, viewTitle.innerText);
      }
    });

    async function deleteMeetingPrompt(id, title) {
      const displayTitle = title || id;
      if (!confirm(`Möchtest du das Meeting "${displayTitle}" samt Audiodateien (MP3 + WAV) und Screenshots endgültig löschen?`)) {
        return;
      }
      try {
        const res = await fetch(`/api/meetings/${id}`, { method: "DELETE" });
        if (res.ok) {
          if (activeMeetingId === id) {
            resetViewer();
          }
          await fetchMeetings();
        } else {
          const err = await res.json();
          alert("Fehler beim Löschen: " + (err.detail || "Unbekannt"));
        }
      } catch (err) {
        alert("Netzwerkfehler beim Löschen: " + err);
      }
    }

    function resetViewer() {
      activeMeetingId = null;
      rawCurrentMarkdown = "";
      if (searchMatchBadge) searchMatchBadge.style.display = "none";
      viewTitle.innerText = "Kein Meeting ausgewählt";
      viewMeta.innerText = "-";
      markdownBody.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <p>Starte eine Aufnahme oder wähle links ein vergangenes Meeting aus,<br>um die Zusammenfassung und das Transkript anzuzeigen.</p>
        </div>
      `;
      copyMdBtn.style.display = "none";
      downloadMdBtn.style.display = "none";
      deleteMeetingBtn.style.display = "none";
      audioPlayerSection.style.display = "none";
      audioElement.src = "";
    }

    let cachedMeetings = [];
    async function fetchMeetings() {
      try {
        const res = await fetch("/api/meetings");
        if (res.ok) {
          cachedMeetings = await res.json();
          meetingCount.innerText = cachedMeetings.length;
          renderMeetingsList();

          const params = new URLSearchParams(window.location.search);
          const urlUser = params.get("user_name");
          if (urlUser) {
            syncUserName(urlUser);
          }
          const autoMeeting = params.get("meeting");
          if (autoMeeting && !activeMeetingId) {
            loadMeeting(autoMeeting);
          }
          if (params.get("open_drawer") === "1") {
            openAttachmentsAccordion();
          }
          if (params.get("open_settings") === "1") {
            settingsModal.classList.add("active");
          }
          if (params.get("scroll") === "protocol") {
            setTimeout(() => {
              const el = document.getElementById("markdownBody");
              if (el) el.scrollIntoView({ behavior: "instant", block: "start" });
            }, 600);
          }
        }
      } catch (e) {
        console.error("Fehler bei Meetings:", e);
      }
    }

    function escapeRegExp(string) {
      return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    function highlightHtmlString(text, query) {
      if (!query || !text) return text || "";
      const trimmed = query.trim();
      if (trimmed.length < 2) return text;
      const escaped = escapeRegExp(trimmed);
      const regex = new RegExp(`(${escaped})`, "gi");
      return text.replace(regex, '<mark class="search-highlight">$1</mark>');
    }

    function highlightTextInElement(container, query) {
      if (!container) return 0;
      removeHighlights(container);

      const trimmed = (query || "").trim();
      if (trimmed.length < 2) return 0;

      const regex = new RegExp(`(${escapeRegExp(trimmed)})`, "gi");
      const walker = document.createTreeWalker(
        container,
        NodeFilter.SHOW_TEXT,
        {
          acceptNode: (node) => {
            if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
            const parent = node.parentNode;
            if (!parent) return NodeFilter.FILTER_REJECT;
            const tag = parent.nodeName.toUpperCase();
            if (tag === "SCRIPT" || tag === "STYLE" || tag === "MARK") {
              return NodeFilter.FILTER_REJECT;
            }
            return NodeFilter.FILTER_ACCEPT;
          }
        }
      );

      const textNodes = [];
      while (walker.nextNode()) {
        textNodes.push(walker.currentNode);
      }

      let matchCount = 0;
      for (const node of textNodes) {
        const val = node.nodeValue;
        if (regex.test(val)) {
          regex.lastIndex = 0;
          const frag = document.createDocumentFragment();
          let lastIdx = 0;
          let match;
          while ((match = regex.exec(val)) !== null) {
            if (match.index > lastIdx) {
              frag.appendChild(document.createTextNode(val.substring(lastIdx, match.index)));
            }
            const mark = document.createElement("mark");
            mark.className = "search-highlight";
            mark.textContent = match[0];
            frag.appendChild(mark);
            matchCount++;
            lastIdx = regex.lastIndex;
          }
          if (lastIdx < val.length) {
            frag.appendChild(document.createTextNode(val.substring(lastIdx)));
          }
          node.parentNode.replaceChild(frag, node);
        }
      }
      return matchCount;
    }

    function removeHighlights(container) {
      if (!container) return;
      const marks = container.querySelectorAll("mark.search-highlight");
      marks.forEach(mark => {
        const textNode = document.createTextNode(mark.textContent);
        if (mark.parentNode) {
          mark.parentNode.replaceChild(textNode, mark);
        }
      });
      container.normalize();
    }

    function applyViewerSearchHighlight(shouldScroll = false) {
      if (!markdownBody) return;
      const query = (searchInput ? searchInput.value : "").trim();
      removeHighlights(markdownBody);

      if (!activeMeetingId) {
        if (searchMatchBadge) searchMatchBadge.style.display = "none";
        return;
      }

      if (query.length < 2) {
        if (searchMatchBadge) searchMatchBadge.style.display = "none";
        return;
      }

      const count = highlightTextInElement(markdownBody, query);

      if (searchMatchBadge) {
        if (count > 0) {
          searchMatchBadge.textContent = `🔍 ${count} Treffer im Protokoll`;
          searchMatchBadge.className = "search-match-badge found";
          searchMatchBadge.style.display = "inline-flex";
        } else {
          searchMatchBadge.textContent = "Kein Treffer im aktuellen Protokoll";
          searchMatchBadge.className = "search-match-badge none";
          searchMatchBadge.style.display = "inline-flex";
        }
      }

      if (shouldScroll && count > 0) {
        setTimeout(() => {
          const firstMark = markdownBody.querySelector("mark.search-highlight");
          if (firstMark) {
            firstMark.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        }, 120);
      }
    }

    searchInput.addEventListener("input", () => {
      const q = (searchInput.value || "").trim();
      if (clearSearchBtn) clearSearchBtn.style.display = q ? "flex" : "none";
      renderMeetingsList();
      applyViewerSearchHighlight(false);
    });

    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        searchInput.value = "";
        if (clearSearchBtn) clearSearchBtn.style.display = "none";
        renderMeetingsList();
        applyViewerSearchHighlight(false);
      }
    });

    if (clearSearchBtn) {
      clearSearchBtn.addEventListener("click", () => {
        searchInput.value = "";
        clearSearchBtn.style.display = "none";
        renderMeetingsList();
        applyViewerSearchHighlight(false);
        searchInput.focus();
      });
    }

    function renderMeetingsList() {
      meetingsList.innerHTML = "";
      const query = (searchInput.value || "").toLowerCase().trim();
      const filtered = cachedMeetings.filter(m => {
        if (!query) return true;
        const t = (m.title || "").toLowerCase();
        const p = (m.participants || "").toLowerCase();
        const d = (m.created_at || "").toLowerCase();
        const c = (m.content || "").toLowerCase();
        return t.includes(query) || p.includes(query) || d.includes(query) || c.includes(query);
      });

      if (filtered.length === 0) {
        meetingsList.innerHTML = `<p style="font-size: 0.8rem; color: var(--text-sub); text-align: center; padding: 1rem;">${cachedMeetings.length === 0 ? "Noch keine Aufnahmen vorhanden." : "Keine Treffer für deine Suche."}</p>`;
        return;
      }

      filtered.forEach(m => {
        const item = document.createElement("div");
        item.className = "meeting-item" + (m.id === activeMeetingId ? " active" : "");
        const d = new Date(m.created_at).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
        const safeTitle = (m.title || m.id).replace(/'/g, "\\'");
        const t = (m.title || "").toLowerCase();
        const p = (m.participants || "").toLowerCase();
        const c = (m.content || "").toLowerCase();
        const isContentMatch = query && !t.includes(query) && !p.includes(query) && c.includes(query);

        item.innerHTML = `
          <div style="padding-right: 28px;">
            <div class="meeting-item-title">${highlightHtmlString(m.title || m.id, query)}</div>
            <div class="meeting-item-date">${d}${m.participants ? ' • ' + m.participants : ''}</div>
            ${isContentMatch ? '<div style="font-size: 0.72rem; color: #818cf8; margin-top: 4px; display: flex; align-items: center; gap: 4px;"><span>💬</span> Treffer im Transkript / Protokoll</div>' : ''}
          </div>
          <button class="delete-item-btn" title="Dieses Meeting löschen" onclick="event.stopPropagation(); deleteMeetingPrompt('${m.id}', '${safeTitle}')">
            <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        `;
        item.onclick = () => loadMeeting(m.id);
        meetingsList.appendChild(item);
      });
    }

    // Status polling loop
    async function pollStatus() {
      try {
        const res = await fetch("/api/status");
        if (res.ok) {
          const data = await res.json();
          currentStatus = data.status;

          // Devices
          micName.innerText = data.mic_device;
          loopbackName.innerText = data.loopback_device;

          // VU meters
          micVuFill.style.width = Math.min(100, Math.round(data.mic_level * 100 * 1.5)) + "%";
          teamsVuFill.style.width = Math.min(100, Math.round(data.loopback_level * 100 * 1.5)) + "%";

          hasApiKeyConfigured = data.has_api_key;
          if (!data.has_api_key) {
            if (!hasSeenWelcomeModal) {
              hasSeenWelcomeModal = true;
              welcomeBanner.style.display = "block";
              settingsModal.classList.add("active");
            }
          } else {
            welcomeBanner.style.display = "none";
          }

          // Status & UI states
          if (data.status === "recording") {
            statusBadge.className = "status-badge recording";
            statusText.innerText = "Aufnahme läuft";
            timerDisplay.innerText = formatTime(data.duration);
            recordToggleBtn.className = "record-btn stop";
            recordBtnText.innerText = "Aufnahme beenden & Analysieren";
            cancelRecordBtn.style.display = "flex";
            pulseRing.style.display = "block";
            processingBanner.style.display = "none";
            meetingTitleInput.disabled = true;
            meetingParticipantsInput.disabled = true;
            meetingTypeSelect.disabled = true;
            if (data.current_title && !meetingTitleInput.value) {
              meetingTitleInput.value = data.current_title;
            }
            if (data.current_participants && !meetingParticipantsInput.value) {
              meetingParticipantsInput.value = data.current_participants;
            }
            if (data.current_meeting_type) {
              meetingTypeSelect.value = data.current_meeting_type;
            }
          } else if (data.status === "processing") {
            statusBadge.className = "status-badge processing";
            statusText.innerText = "Gemini analysiert...";
            recordToggleBtn.className = "record-btn";
            recordToggleBtn.disabled = true;
            recordBtnText.innerText = "KI-Analyse läuft...";
            cancelRecordBtn.style.display = "none";
            pulseRing.style.display = "none";
            processingBanner.style.display = "flex";
            processStepText.innerText = data.process_step || "Verarbeite...";
            meetingTitleInput.disabled = true;
            meetingParticipantsInput.disabled = true;
            meetingTypeSelect.disabled = true;
          } else {
            statusBadge.className = data.has_api_key ? "status-badge" : "status-badge warning";
            statusText.innerText = data.has_api_key ? "Bereit" : "API-Key fehlt";
            recordToggleBtn.disabled = false;
            recordToggleBtn.className = "record-btn start";
            recordBtnText.innerText = "Aufnahme starten";
            cancelRecordBtn.style.display = "none";
            pulseRing.style.display = "none";
            processingBanner.style.display = "none";
            meetingTitleInput.disabled = false;
            meetingParticipantsInput.disabled = false;
            meetingTypeSelect.disabled = false;
            if (data.duration === 0) {
              timerDisplay.innerText = "00:00:00";
            }

            // Falls gerade ein Meeting fertig analysiert wurde
            if (data.last_meeting_id && data.last_meeting_id !== activeMeetingId) {
              fetchMeetings();
              loadMeeting(data.last_meeting_id);
            }
          }

          if (data.model) {
            currentConfiguredModel = data.model;
            if (!settingsModal.classList.contains("active")) {
              syncModelSelect(data.model);
            }
          }
        }
      } catch (err) {
        console.error("Poll Error:", err);
      }
    }

    // Warnung vor versehentlichem Tab-Schließen bei laufender Aufnahme
    window.addEventListener("beforeunload", (e) => {
      if (currentStatus === "recording") {
        e.preventDefault();
        e.returnValue = "Eine Aufnahme läuft aktuell im Hintergrund weiter. Du kannst dieses Fenster jederzeit wieder aufrufen.";
      }
    });

    // Initialize
    setInterval(pollStatus, 300);
    fetchMeetings();