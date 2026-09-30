// State
    let currentStatus = "idle";
    let activeMeetingId = null;
    let activeMeetingMeta = null;
    let rawCurrentMarkdown = "";
    let hasSeenWelcomeModal = false;
    let hasApiKeyConfigured = false;
    let currentConfiguredModel = "gemini-flash-latest";
    const API_KEY_MASK = "••••••••••••••••••••••••";
    let lastAutoLoadedMeetingId = null; // a freshly analyzed meeting is opened automatically only once
    let defaultAiActMode = true; // recording mode from the settings (EU AI Act compliant or with sentiment analysis)
    const DEVICE_STORAGE_KEYS = { mic: "ghostscribe_mic_device", loopback: "ghostscribe_loopback_device" };
    const TRANSCRIPT_STORAGE_KEY = "ghostscribe_transcript_language";
    let transcriptLanguage = localStorage.getItem(TRANSCRIPT_STORAGE_KEY) || "original";
    let transcriptHasTranslation = false;
    let voiceRecognitionEnabled = false;
    let voiceWorkers = 1; // parallel processes for the voice recognition, at most voiceWorkersMax
    let voiceWorkersMax = 1;
    const TRASH_ICON = '<svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>';

    // Creates an element; text is always set as textContent and never parsed as HTML
    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function isBusy() {
      return currentStatus === "recording" || currentStatus === "processing";
    }

    function meetingDate(meta, options) {
      return i18n.date(meta.meeting_start || meta.created_at, options);
    }

    // Error message returned by the server (already translated), or a generic fallback
    const errorText = (data) => (typeof data?.detail === "string" ? data.detail : t("common.unknown"));

    function syncModelSelect(modelName) {
      if (!modelSelect || !modelName) return;
      let opt = [...modelSelect.options].find(o => o.value === modelName);
      if (!opt) {
        opt = document.createElement("option");
        opt.value = modelName;
        opt.textContent = t("settings.model_configured", { model: modelName });
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
    const micSelect = document.getElementById("micSelect");
    const loopbackSelect = document.getElementById("loopbackSelect");
    const errorBanner = document.getElementById("errorBanner");
    const unprocessedSection = document.getElementById("unprocessedSection");
    const unprocessedList = document.getElementById("unprocessedList");
    const micVuFill = document.getElementById("micVuFill");
    const teamsVuFill = document.getElementById("teamsVuFill");
    const timerDisplay = document.getElementById("timerDisplay");
    const meetingTitleInput = document.getElementById("meetingTitleInput");
    const meetingParticipantsInput = document.getElementById("meetingParticipantsInput");
    const participantsField = document.getElementById("participantsField");
    const meetingTypeSelect = document.getElementById("meetingTypeSelect");
    const cancelRecordBtn = document.getElementById("cancelRecordBtn");
    const recordToggleBtn = document.getElementById("recordToggleBtn");
    const recordBtnText = document.getElementById("recordBtnText");
    const pulseRing = document.getElementById("pulseRing");
    const processingBanner = document.getElementById("processingBanner");
    const processStepText = document.getElementById("processStepText");
    const contentGrid = document.getElementById("contentGrid");
    const meetingsToggle = document.getElementById("meetingsToggle");
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
    const closeMeetingBtn = document.getElementById("closeMeetingBtn");
    const audioPlayerSection = document.getElementById("audioPlayerSection");
    const audioElement = document.getElementById("audioElement");
    const userSpeakerName = document.getElementById("userSpeakerName");

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

    // Own name in the minutes (next to the microphone), saved in the browser, with dynamic auto-resizing
    function adjustUserSpeakerInputWidth() {
      const text = userSpeakerName.value || userSpeakerName.placeholder;
      const dynamicWidth = Math.max(54, Math.min(220, text.length * 8.6 + 18));
      userSpeakerName.style.width = dynamicWidth + "px";
    }

    userSpeakerName.value = localStorage.getItem("ghostscribe_user_name") || "";
    adjustUserSpeakerInputWidth();
    userSpeakerName.addEventListener("input", () => {
      adjustUserSpeakerInputWidth();
      localStorage.setItem("ghostscribe_user_name", userSpeakerName.value);
      renderParticipantChips(); // the own name has a color of its own
    });

    function ownName() {
      return userSpeakerName.value.trim() || userSpeakerName.placeholder;
    }

    // Participants as colored chips: a comma or Enter turns the typed name into a chip. Every person keeps
    // the chip color in the minutes (see colorSpeakers); the own name has a color of its own.
    const SPEAKER_COLORS = 8;
    let participantNames = [];

    function splitNames(text) {
      return (text || "").split(",").map(name => name.trim()).filter(Boolean);
    }

    // "Sarah (Lead Architect)" and "sarah" are the same person
    function speakerKey(name) {
      return name.replace(/\([^)]*\)/g, "").trim().toLowerCase();
    }

    function participantChip(name, index, selfKey) {
      const color = speakerKey(name) === selfKey ? "speaker-self" : `speaker-${index % SPEAKER_COLORS}`;
      return el("span", `participant-chip ${color}`, name);
    }

    function participantsValue() {
      return [...participantNames, ...splitNames(meetingParticipantsInput.value)].join(", ");
    }

    function setParticipants(text) {
      participantNames = [];
      meetingParticipantsInput.value = "";
      addParticipants(splitNames(text));
      renderParticipantChips();
    }

    function addParticipants(names) {
      const added = names.map(name => name.trim()).filter(name => name && !participantNames.some(known => speakerKey(known) === speakerKey(name)));
      participantNames.push(...added);
      if (added.length) renderParticipantChips();
    }

    function renderParticipantChips() {
      const selfKey = speakerKey(ownName());
      participantsField.querySelectorAll(".participant-chip").forEach(chip => chip.remove());
      participantNames.forEach((name, index) => {
        const chip = participantChip(name, index, selfKey);
        const remove = el("button", "participant-chip-remove", "×");
        remove.type = "button";
        remove.title = t("console.remove_participant", { name });
        remove.addEventListener("mousedown", (e) => e.preventDefault()); // keeps the focus (and typed text) in the input
        remove.addEventListener("click", () => {
          participantNames.splice(index, 1);
          renderParticipantChips();
        });
        chip.append(remove);
        meetingParticipantsInput.before(chip);
      });
      participantsField.classList.toggle("has-chips", participantNames.length > 0);
    }

    meetingParticipantsInput.addEventListener("input", () => {
      const parts = meetingParticipantsInput.value.split(",");
      if (parts.length < 2) return;
      meetingParticipantsInput.value = parts.pop().trimStart();
      addParticipants(parts);
    });
    meetingParticipantsInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addParticipants([meetingParticipantsInput.value]);
        meetingParticipantsInput.value = "";
      } else if (e.key === "Backspace" && !meetingParticipantsInput.value && participantNames.length) {
        e.preventDefault();
        meetingParticipantsInput.value = participantNames.pop(); // back into the field for editing
        renderParticipantChips();
      }
    });
    meetingParticipantsInput.addEventListener("blur", () => {
      addParticipants([meetingParticipantsInput.value]);
      meetingParticipantsInput.value = "";
    });
    participantsField.addEventListener("click", (e) => {
      if (e.target === participantsField) meetingParticipantsInput.focus();
    });

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

    const voiceRecognitionSelect = document.getElementById("voiceRecognitionSelect");
    const voiceWorkersSelect = document.getElementById("voiceWorkersSelect");
    const voiceProfilesList = document.getElementById("voiceProfilesList");
    const apiKeyHint = document.getElementById("apiKeyHint");
    const defaultAiActSelect = document.getElementById("defaultAiActSelect");
    const modeHint = document.getElementById("modeHint");
    const sentimentModeWarning = document.getElementById("sentimentModeWarning");

    // Sentiment Warning Confirmation Modal Elements
    const sentimentConfirmModal = document.getElementById("sentimentConfirmModal");
    const confirmSentimentBtn = document.getElementById("confirmSentimentBtn");
    const cancelSentimentBtn = document.getElementById("cancelSentimentBtn");
    const closeSentimentModalX = document.getElementById("closeSentimentModalX");

    // Choosing the sentiment mode in the settings needs a confirmation of the legal notice
    function openSentimentWarning() {
      sentimentConfirmModal.classList.add("active");
    }

    function closeSentimentWarning(confirmed = false) {
      sentimentConfirmModal.classList.remove("active");
      if (!confirmed) defaultAiActSelect.value = "true";
      renderModeHint();
    }

    // The hint below the analysis mode and the warning next to the status follow the mode
    function renderModeHint() {
      const sentiment = defaultAiActSelect.value === "false";
      modeHint.textContent = t(sentiment ? "settings.mode_hint_sentiment" : "settings.mode_hint");
      modeHint.classList.toggle("warning", sentiment);
    }

    function renderModeWarning() {
      sentimentModeWarning.hidden = defaultAiActMode;
    }

    sentimentModeWarning.addEventListener("click", () => settingsBtn.click());

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

    voiceRecognitionSelect.addEventListener("change", () => {
      voiceWorkersSelect.disabled = voiceRecognitionSelect.value !== "true";
    });

    defaultAiActSelect.addEventListener("change", () => {
      renderModeHint();
      if (defaultAiActSelect.value === "false") openSentimentWarning();
    });

    // Settings Modal handlers
    function renderApiKeyStatus() {
      welcomeBanner.style.display = hasApiKeyConfigured ? "none" : "block";
      apiKeyHint.innerHTML = DOMPurify.sanitize(t(hasApiKeyConfigured ? "settings.api_key_hint_saved" : "settings.api_key_hint_new"));
      apiKeyHint.style.color = hasApiKeyConfigured ? "var(--emerald)" : "var(--text-sub)";
    }

    function updateSettingsModalUI() {
      defaultAiActSelect.value = defaultAiActMode ? "true" : "false";
      renderModeHint();
      voiceRecognitionSelect.value = voiceRecognitionEnabled ? "true" : "false";
      voiceWorkersSelect.replaceChildren(
        ...Array.from({ length: voiceWorkersMax }, (_, i) => new Option(i18n.number(i + 1), String(i + 1)))
      );
      voiceWorkersSelect.value = String(voiceWorkers);
      voiceWorkersSelect.disabled = !voiceRecognitionEnabled;
      loadVoiceProfiles();
      syncModelSelect(currentConfiguredModel);
      renderApiKeyStatus();
      apiKeyInput.value = hasApiKeyConfigured ? API_KEY_MASK : "";
      apiKeyInput.placeholder = "AIzaSy...";
    }

    // Intuitive edit-on-focus for API Key without cluttered extra buttons
    apiKeyInput.addEventListener("focus", () => {
      if (apiKeyInput.value.includes("•")) {
        apiKeyInput.value = "";
        apiKeyInput.placeholder = t("settings.api_key_new_placeholder");
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
        showToast(t("toast.enter_api_key"));
        apiKeyInput.focus();
        return;
      }

      const payload = {
        model: model,
        default_ai_act_mode: defaultAiActSelect.value === "true",
        voice_recognition: voiceRecognitionSelect.value === "true",
        voice_workers: Number(voiceWorkersSelect.value)
      };
      if (!isMaskedOrEmpty) {
        payload.api_key = key;
      }

      const origText = saveSettingsBtn.innerText;
      saveSettingsBtn.disabled = true;
      saveSettingsBtn.innerText = t("settings.saving");

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
          voiceRecognitionEnabled = payload.voice_recognition;
          voiceWorkers = payload.voice_workers;
          syncModelSelect(model);
          if (welcomeBanner && hasApiKeyConfigured) welcomeBanner.style.display = "none";
          defaultAiActMode = payload.default_ai_act_mode;
          renderModeWarning();
          settingsModal.classList.remove("active");
          showToast(t("toast.settings_saved"));
          pollStatus();
        } else {
          const errData = await res.json().catch(() => ({}));
          showToast(t("toast.save_failed", { message: errorText(errData) }));
        }
      } catch (err) {
        showToast(t("toast.save_failed", { message: err }));
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
          attachmentsCountBadge.innerText = t("attachments.badge_with_chat", { images: t("attachments.badge_images", { count: imgCount }) });
        } else if (imgCount > 0) {
          attachmentsCountBadge.innerText = t("attachments.badge_images", { count: imgCount });
        } else {
          attachmentsCountBadge.innerText = t("attachments.badge_chat");
        }
      }
    }

    function updateChatStats() {
      if (!chatInput || !chatCharCount) return;
      const len = chatInput.value.length;
      chatCharCount.innerText = t("attachments.char_count", { count: len });
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
            showToast(t("toast.clipboard_empty"));
            return;
          }
          const prefix = (chatInput && chatInput.value.trim()) ? "\n\n" : "";
          if (chatInput) {
            chatInput.value = chatInput.value + prefix + text.trim();
            updateChatStats();
            showToast(t("toast.clipboard_pasted", { count: text.trim().length }));
          }
        } catch (err) {
          showToast(t("toast.clipboard_tip"));
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
        const card = el("div", "thumbnail-card");
        card.title = t("attachments.thumbnail_title", { name: img.filename, size: img.size });
        const image = el("img", "thumbnail-img");
        image.src = img.data;
        image.alt = img.filename;
        const removeBtn = el("button", "thumbnail-del", "✕");
        removeBtn.type = "button";
        removeBtn.title = t("attachments.remove");
        removeBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          removeAttachment(img.id);
        });
        card.append(image, el("span", "thumbnail-badge", `#${idx + 1}`), removeBtn);
        card.onclick = () => openLightbox(img.data, `${img.filename} (#${idx + 1}) • ${img.size}`);
        thumbnailsContainer.appendChild(card);
      });
    }

    function removeAttachment(id) {
      attachedImages = attachedImages.filter(item => item.id !== id);
      renderThumbnails();
      updateAttachmentsBadge();
    }

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
                chatInput.value = chatInput.value + prefix + t("attachments.file_marker", { name: file.name }) + "\n" + textContent.trim() + "\n";
                updateChatStats();
                showToast(t("toast.text_file_imported", { name: file.name }));
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
          showToast(t("toast.images_added", { count: imgCount }));
        }
      }
    }

    // Global Strg+V Paste Handler for Screenshots, Files & Text
    window.addEventListener("paste", (e) => {
      if (!contextRecording) return; // chat and slides are added after the recording
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
        showToast(t("toast.screenshot_pasted"));
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
          showToast(t("toast.text_pasted", { count: pastedText.trim().length }));
        }
      }
    });

    // Toggle Record
    const selectedDevice = (select) => (select.value === "" ? null : Number(select.value));

    recordToggleBtn.addEventListener("click", async () => {
      if (contextRecording && !isBusy()) {
        startAnalysis();
      } else if (!isBusy()) {
        if (!hasApiKeyConfigured) {
          welcomeBanner.style.display = "block";
          settingsModal.classList.add("active");
          apiKeyInput.focus();
          return;
        }
        const title = meetingTitleInput.value.trim();
        const participants = participantsValue();
        const meetingType = meetingTypeSelect.value;
        const userName = ownName();
        try {
          const res = await fetch("/api/record/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              title: title,
              participants: participants,
              meeting_type: meetingType,
              user_name: userName,
              ai_act_mode: defaultAiActMode,
              mic_device: selectedDevice(micSelect),
              loopback_device: selectedDevice(loopbackSelect)
            })
          });
          if (!res.ok) {
            alert(t("alert.start_failed", { message: errorText(await res.json().catch(() => ({}))) }));
          }
        } catch (e) {
          alert(t("alert.network_error", { message: e }));
        }
      } else if (currentStatus === "recording") {
        try {
          const res = await fetch("/api/record/stop", { method: "POST" });
          if (!res.ok) {
            alert(t("alert.stop_failed", { message: errorText(await res.json().catch(() => ({}))) }));
          }
        } catch (e) {
          alert(t("alert.network_error", { message: e }));
        }
      }
    });

    // Cancel Record
    cancelRecordBtn.addEventListener("click", async () => {
      if (confirm(t("record.confirm_discard"))) {
        try {
          const res = await fetch("/api/record/cancel", { method: "POST" });
          if (res.ok) {
            clearAttachments();
            pollStatus();
          }
        } catch (e) {
          alert(t("alert.discard_failed", { message: e }));
        }
      }
    });

    // Smart 1-Click Copy: Formatted Rich HTML (Teams, Outlook, Slack, Word) + Clean Markdown (Notepad, Code)
    copyMdBtn.addEventListener("click", async () => {
      if (!rawCurrentMarkdown) return;
      const markdown = visibleMarkdown(); // the transcript in the language that is shown
      try {
        const htmlContent = DOMPurify.sanitize(marked.parse(markdown));
        const blobHtml = new Blob([htmlContent], { type: "text/html" });
        const blobText = new Blob([markdown], { type: "text/plain" });

        if (navigator.clipboard && window.ClipboardItem) {
          await navigator.clipboard.write([
            new ClipboardItem({
              "text/html": blobHtml,
              "text/plain": blobText,
            })
          ]);
        } else {
          await navigator.clipboard.writeText(markdown);
        }
        flashButton(copyMdBtn);
        showToast(t("toast.copied_rich"));
      } catch (err) {
        try {
          await navigator.clipboard.writeText(markdown);
          flashButton(copyMdBtn);
          showToast(t("toast.copied_text"));
        } catch (e) {
          showToast(t("toast.copy_failed"));
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

    function renderViewerMeta(meta) {
      const isAiAct = meta.ai_act_mode !== false;
      const modeBadge = el("span", `badge-tag ${isAiAct ? "ai-act" : "sentiment"}`, t(isAiAct ? "viewer.badge_ai_act" : "viewer.badge_sentiment"));
      modeBadge.title = t(isAiAct ? "viewer.badge_ai_act_title" : "viewer.badge_sentiment_title");
      const details = [t("viewer.meeting_on", { date: meetingDate(meta, { dateStyle: "long", timeStyle: "short" }) }), t("viewer.model", { model: meta.model_used })];
      viewMeta.replaceChildren(details.join(" • ") + " ", modeBadge);
      const names = splitNames(meta.participants);
      if (names.length) {
        const selfKey = speakerKey(meta.user_name || "");
        const row = el("div", "viewer-participants");
        row.append(el("span", "", t("viewer.participants")), ...names.map((name, index) => participantChip(name, index, selfKey)));
        viewMeta.append(row);
      }
    }

    // Speaker names in the minutes get the colors of the participant chips. Further speakers of the transcript
    // follow in the order they first speak; "Tom" matches the participant "Tom Weber" if the first name is unique.
    function colorSpeakers(meta) {
      const selfKey = speakerKey(meta.user_name || "");
      const keys = splitNames(meta.participants).map(speakerKey);
      const firstName = key => key.split(" ")[0];
      const known = key => {
        if (keys.includes(key)) return key;
        const sameFirstName = keys.filter(other => firstName(other) === firstName(key));
        return sameFirstName.length === 1 ? sameFirstName[0] : null;
      };
      const labels = [...markdownBody.querySelectorAll("strong")].map(strong => [strong, speakerKey(strong.textContent.replace(/:\s*$/, ""))]);
      for (const [strong, key] of labels) {
        const speaksInTranscript = /:\s*$/.test(strong.textContent) && /^\[\d{2}:\d{2}:\d{2}\]/.test(strong.parentElement.textContent.trim());
        if (speaksInTranscript && key && key !== selfKey && !known(key)) keys.push(key);
      }
      for (const [strong, key] of labels) {
        const person = key && key !== selfKey ? known(key) : null;
        if (key && key === selfKey) strong.classList.add("speaker", "speaker-self");
        else if (person) strong.classList.add("speaker", `speaker-${keys.indexOf(person) % SPEAKER_COLORS}`);
      }
    }

    // Transcripts in languages other than German and English carry a German translation below each line
    // ("  > ..."). The viewer shows either the original or the translation; the download keeps both.
    const TRANSCRIPT_ENTRY = /^(- \[\d{2}:\d{2}:\d{2}\] \*\*[^*]+\*\*(?: \[[^\]]*\])?:? ?)(.*)$/;
    const TRANSLATION_LINE = /^\s*> ?(.*)$/;

    function transcriptVariant(markdown, language) {
      const lines = [];
      let translated = false;
      for (const line of markdown.split(/\r?\n/)) {
        const translation = line.match(TRANSLATION_LINE);
        const entry = translation && lines.length ? lines[lines.length - 1].match(TRANSCRIPT_ENTRY) : null;
        if (!entry) {
          lines.push(line);
          translated = false;
        } else if (language === "german") {
          lines[lines.length - 1] = translated ? `${lines[lines.length - 1]} ${translation[1]}` : entry[1] + translation[1];
          translated = true;
        }
      }
      return lines.join("\n");
    }

    function visibleMarkdown() {
      return transcriptHasTranslation ? transcriptVariant(rawCurrentMarkdown, transcriptLanguage) : rawCurrentMarkdown;
    }

    function renderMarkdown() {
      markdownBody.innerHTML = DOMPurify.sanitize(marked.parse(visibleMarkdown()));
      if (transcriptHasTranslation) addTranscriptToggle();
      if (activeMeetingMeta) colorSpeakers(activeMeetingMeta);
      if (audioElement.getAttribute("src")) linkTimestamps();
    }

    // [HH:MM:SS] in the minutes plays the recording from a few seconds before that moment
    const TIMESTAMP = /\[(\d{2}):(\d{2}):(\d{2})\]/g;
    const TIMESTAMP_LEAD_SECONDS = 1;

    function linkTimestamps() {
      const walker = document.createTreeWalker(markdownBody, NodeFilter.SHOW_TEXT);
      const texts = [];
      while (walker.nextNode()) texts.push(walker.currentNode);
      for (const text of texts) {
        const matches = [...text.nodeValue.matchAll(TIMESTAMP)];
        if (!matches.length) continue;
        const parts = [];
        let end = 0;
        for (const match of matches) {
          const link = el("button", "timestamp-link", match[0]);
          link.type = "button";
          link.title = t("viewer.play_from", { seconds: TIMESTAMP_LEAD_SECONDS });
          link.dataset.seconds = Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
          parts.push(text.nodeValue.slice(end, match.index), link);
          end = match.index + match[0].length;
        }
        text.replaceWith(...parts, text.nodeValue.slice(end));
      }
    }

    markdownBody.addEventListener("click", (e) => {
      const link = e.target.closest(".timestamp-link");
      if (!link) return;
      audioElement.currentTime = Math.max(0, Number(link.dataset.seconds) - TIMESTAMP_LEAD_SECONDS);
      audioElement.play();
    });

    function addTranscriptToggle() {
      const heading = [...markdownBody.querySelectorAll("h2")].find(h => /Transkript|Transcript/i.test(h.textContent));
      if (!heading) return;
      const toggle = el("span", "transcript-toggle");
      toggle.title = t("viewer.transcript_toggle_title");
      for (const [language, key] of [["original", "viewer.transcript_original"], ["german", "viewer.transcript_german"]]) {
        const button = el("button", `transcript-toggle-btn${language === transcriptLanguage ? " active" : ""}`, t(key));
        button.type = "button";
        button.addEventListener("click", () => setTranscriptLanguage(language));
        toggle.append(button);
      }
      heading.append(toggle);
    }

    function setTranscriptLanguage(language) {
      transcriptLanguage = language;
      localStorage.setItem(TRANSCRIPT_STORAGE_KEY, language);
      renderMarkdown();
      applyViewerSearchHighlight(false);
    }

    // Voices of the meeting (local voice recognition): recognized profiles and unknown voices to name
    const voicesPanel = document.getElementById("voicesPanel");

    function renderVoices(meta) {
      const voices = meta.voices || [];
      voicesPanel.hidden = voices.length === 0;
      voicesPanel.replaceChildren(el("div", "voices-title", t("viewer.voices_title")), ...voices.map(voiceRow));
    }

    function voiceRow(voice) {
      const status = voice.confirmed
        ? t("viewer.voice_confirmed")
        : voice.profile_id
          ? t("viewer.voice_recognized", { percent: Math.round(voice.similarity * 100) })
          : t("viewer.voice_unknown");
      const info = el("div", "voice-info");
      info.append(
        el("strong", "voice-label", voice.label),
        el("span", `voice-status${voice.profile_id ? " known" : ""}`, status),
        el("span", "voice-time", t("viewer.voice_speaking_time", { time: formatTime(voice.seconds) }))
      );

      const play = el("button", "mini-action-btn", t("viewer.voice_play"));
      play.type = "button";
      play.addEventListener("click", () => {
        audioElement.currentTime = voice.intervals[0][0];
        audioElement.play();
      });

      const name = el("input", "form-input voice-name-input");
      name.type = "text";
      name.maxLength = 60;
      name.placeholder = t("viewer.voice_name_placeholder");
      if (voice.profile_id) name.value = voice.label;
      const consent = el("input");
      consent.type = "checkbox";
      const consentLabel = el("label", "voice-consent");
      consentLabel.append(consent, t("viewer.voice_consent"));
      const save = el("button", "mini-action-btn", t("viewer.voice_save"));
      save.type = "button";
      save.addEventListener("click", () => saveVoice(voice.label, name.value.trim(), consent.checked));

      const row = el("div", "voice-row");
      const form = el("div", "voice-form");
      form.append(name, consentLabel, save);
      row.append(info, play, form);
      return row;
    }

    async function saveVoice(label, name, consent) {
      if (!consent) {
        showToast(t("toast.voice_consent_missing"));
        return;
      }
      try {
        const res = await fetch(`/api/meetings/${encodeURIComponent(activeMeetingId)}/voices`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label, name, consent })
        });
        if (!res.ok) {
          alert(t("alert.voice_save_failed", { message: errorText(await res.json().catch(() => ({}))) }));
          return;
        }
        showToast(t("toast.voice_saved", { name }));
        await loadMeeting(activeMeetingId);
        fetchMeetings();
      } catch (err) {
        alert(t("alert.network_error", { message: err }));
      }
    }

    // Saved voice profiles in the settings
    async function loadVoiceProfiles() {
      try {
        const res = await fetch("/api/voices");
        if (!res.ok) return;
        const profiles = await res.json();
        voiceProfilesList.replaceChildren(
          ...(profiles.length ? profiles.map(profileItem) : [el("li", "voice-profiles-empty", t("settings.voice_profiles_empty"))])
        );
      } catch (err) {
        console.error("Loading the voice profiles failed:", err);
      }
    }

    function profileItem(profile) {
      const remove = el("button", "mini-action-btn danger", "✕");
      remove.type = "button";
      remove.title = t("settings.voice_profile_delete");
      remove.addEventListener("click", async () => {
        if (!confirm(t("confirm.delete_voice", { name: profile.name }))) return;
        const res = await fetch(`/api/voices/${encodeURIComponent(profile.id)}`, { method: "DELETE" });
        if (res.ok) {
          showToast(t("toast.voice_deleted"));
          loadVoiceProfiles();
        } else {
          alert(t("alert.delete_failed", { message: errorText(await res.json().catch(() => ({}))) }));
        }
      });
      const item = el("li", "voice-profile");
      item.append(
        el("span", "voice-label", profile.name),
        el("span", "voice-time", t("settings.voice_profile_meta", { time: formatTime(profile.seconds), count: profile.samples })),
        remove
      );
      return item;
    }

    // Load meeting details
    async function loadMeeting(id) {
      try {
        const res = await fetch(`/api/meetings/${encodeURIComponent(id)}`);
        if (!res.ok) return;
        const data = await res.json();
        const meta = data.metadata;

        activeMeetingId = id;
        activeMeetingMeta = meta;
        rawCurrentMarkdown = data.markdown;
        transcriptHasTranslation = transcriptVariant(data.markdown, "original") !== data.markdown.replace(/\r\n/g, "\n");

        viewTitle.innerText = meta.title || id;
        renderViewerMeta(meta);
        renderVoices(meta);
        contentGrid.classList.add("meeting-open");

        if (data.audio_url) {
          audioElement.src = data.audio_url;
          audioPlayerSection.style.display = "flex";
        } else {
          audioElement.removeAttribute("src");
          audioPlayerSection.style.display = "none";
        }

        renderMarkdown();
        applyViewerSearchHighlight(true);
        renderMeetingsList();
      } catch (err) {
        console.error("Loading the meeting failed:", err);
      }
    }

    // Audio player in the design of the page (the audio element itself has no visible controls)
    const playPauseBtn = document.getElementById("playPauseBtn");
    const playerSeek = document.getElementById("playerSeek");
    const playerTime = document.getElementById("playerTime");
    const playerDuration = document.getElementById("playerDuration");
    const playerSpeed = document.getElementById("playerSpeed");
    const playerMute = document.getElementById("playerMute");
    const PLAYBACK_SPEEDS = [1, 1.25, 1.5, 2];

    function renderPlayer() {
      const duration = Number.isFinite(audioElement.duration) ? audioElement.duration : 0;
      const progress = duration ? audioElement.currentTime / duration : 0;
      playerSeek.value = Math.round(progress * 1000);
      playerSeek.style.setProperty("--progress", `${progress * 100}%`);
      playerTime.textContent = formatTime(audioElement.currentTime);
      playerDuration.textContent = formatTime(duration);
      playPauseBtn.classList.toggle("playing", !audioElement.paused);
      playerMute.classList.toggle("muted", audioElement.muted);
      playerSpeed.textContent = `${i18n.number(audioElement.playbackRate)}×`;
    }

    ["timeupdate", "durationchange", "loadedmetadata", "play", "pause", "ended", "emptied", "ratechange", "volumechange"]
      .forEach(event => audioElement.addEventListener(event, renderPlayer));
    playPauseBtn.addEventListener("click", () => (audioElement.paused ? audioElement.play() : audioElement.pause()));
    playerSeek.addEventListener("input", () => {
      if (audioElement.duration) audioElement.currentTime = (playerSeek.value / 1000) * audioElement.duration;
    });
    playerSpeed.addEventListener("click", () => {
      const next = PLAYBACK_SPEEDS[(PLAYBACK_SPEEDS.indexOf(audioElement.playbackRate) + 1) % PLAYBACK_SPEEDS.length];
      audioElement.defaultPlaybackRate = audioElement.playbackRate = next; // kept when the next meeting is opened
    });
    playerMute.addEventListener("click", () => {
      audioElement.muted = !audioElement.muted;
    });

    // Recordings are mono MP3s with (L + R) / 2, older ones stereo (left: microphone, right: system audio).
    // The gain node plays both on both ears: 1.6 x (L + R) / 2 keeps the loudness of a single speaker.
    let audioContext = null;

    audioElement.addEventListener("play", () => {
      if (!audioContext) {
        audioContext = new AudioContext();
        const mono = new GainNode(audioContext, { gain: 1.6, channelCount: 1, channelCountMode: "explicit" });
        audioContext.createMediaElementSource(audioElement).connect(mono).connect(audioContext.destination);
      }
      if (audioContext.state === "suspended") audioContext.resume();
    });

    // Delete Meeting button handler
    deleteMeetingBtn.addEventListener("click", () => {
      if (activeMeetingId) {
        deleteMeetingPrompt(activeMeetingId, viewTitle.innerText);
      }
    });

    async function deleteMeetingPrompt(id, title) {
      const displayTitle = title || id;
      if (!confirm(t("confirm.delete_meeting", { name: displayTitle }))) {
        return;
      }
      try {
        const res = await fetch(`/api/meetings/${encodeURIComponent(id)}`, { method: "DELETE" });
        if (res.ok) {
          if (activeMeetingId === id) {
            closeMeeting();
          }
          await fetchMeetings();
        } else {
          alert(t("alert.delete_failed", { message: errorText(await res.json().catch(() => ({}))) }));
        }
      } catch (err) {
        alert(t("alert.network_error", { message: err }));
      }
    }

    // Closes the minutes; the meetings list takes the full width again
    function closeMeeting() {
      activeMeetingId = null;
      activeMeetingMeta = null;
      rawCurrentMarkdown = "";
      audioElement.src = "";
      contentGrid.classList.remove("meeting-open");
      renderMeetingsList();
    }

    closeMeetingBtn.addEventListener("click", closeMeeting);

    // The saved meetings start collapsed and open with a click on their heading
    meetingsToggle.addEventListener("click", () => {
      meetingsToggle.setAttribute("aria-expanded", String(contentGrid.classList.toggle("list-open")));
    });

    let cachedMeetings = [];
    async function fetchMeetings() {
      try {
        const res = await fetch("/api/meetings");
        if (res.ok) {
          cachedMeetings = await res.json();
          meetingCount.innerText = cachedMeetings.length;
          renderMeetingsList();
        }
      } catch (e) {
        console.error("Loading the meetings failed:", e);
      }
      fetchUnprocessed();
    }

    // Deep links, e.g. ?meeting=<id>&scroll=protocol (also used for documentation screenshots)
    function applyUrlParams() {
      const params = new URLSearchParams(window.location.search);
      if (params.get("meeting")) loadMeeting(params.get("meeting"));
      if (params.get("open_settings") === "1") settingsModal.classList.add("active");
      if (params.get("scroll") === "protocol") {
        setTimeout(() => markdownBody.scrollIntoView({ behavior: "instant", block: "start" }), 600);
      }
    }

    // Recordings without protocol, e.g. after a rate limit: analyze again or delete
    async function fetchUnprocessed() {
      try {
        const res = await fetch("/api/unprocessed-recordings");
        if (res.ok) renderUnprocessed(await res.json());
      } catch (err) {
        console.error("Loading the unprocessed recordings failed:", err);
      }
    }

    function renderUnprocessed(recordings) {
      unprocessedRecordings = recordings;
      unprocessedList.replaceChildren(...recordings.map(rec => {
        const item = el("div", "unprocessed-item");
        const info = el("div", "unprocessed-info");
        const size = t("sidebar.size_mb", { size: i18n.number(rec.size_kb / 1024, { maximumFractionDigits: 1 }) });
        const recordedAt = i18n.date(rec.recorded_at, { dateStyle: "short", timeStyle: "short" });
        info.append(el("div", "unprocessed-name", rec.title || rec.filename), el("div", "meeting-item-date", `${recordedAt} • ${size}`));
        info.title = rec.filename;
        const analyzeBtn = el("button", "mini-action-btn", t("sidebar.analyze"));
        analyzeBtn.addEventListener("click", () => analyzeRecording(rec.filename));
        const deleteBtn = el("button", "mini-action-btn danger", "✕");
        deleteBtn.title = t("sidebar.delete_recording");
        deleteBtn.addEventListener("click", () => deleteRecording(rec.filename));
        item.append(info, analyzeBtn, deleteBtn);
        return item;
      }));
      unprocessedSection.hidden = isBusy() || recordings.length === 0;
    }

    // After a recording (or for one from the list): add chat history and slides, then start the analysis
    const contextHint = document.getElementById("contextHint");
    const laterBtn = document.getElementById("laterBtn");
    let contextRecording = null; // file name of the recording whose context step is open
    let dismissedPending = null; // a just-saved recording that was put aside with "Later"
    let unprocessedRecordings = [];

    function showContextStep(recording) {
      contextRecording = recording.filename;
      if (recording.title !== undefined) meetingTitleInput.value = recording.title;
      if (recording.participants !== undefined) setParticipants(recording.participants);
      if (recording.meeting_type) meetingTypeSelect.value = recording.meeting_type;
      if (recording.chat_text) chatInput.value = recording.chat_text;
      updateChatStats();
      updateAttachmentsBadge();
      contextHint.hidden = false;
      attachmentsAccordion.hidden = false;
      laterBtn.hidden = false;
      openAttachmentsAccordion();
      recordToggleBtn.classList.add("analyze");
      recordBtnText.innerText = t("record.analyze");
    }

    function endContextStep() {
      dismissedPending = contextRecording;
      contextRecording = null;
      contextHint.hidden = true;
      attachmentsAccordion.hidden = true;
      laterBtn.hidden = true;
      clearAttachments();
      recordToggleBtn.classList.remove("analyze");
      recordBtnText.innerText = t("record.start");
    }

    function contextPayload() {
      return {
        title: meetingTitleInput.value.trim(),
        participants: participantsValue(),
        meeting_type: meetingTypeSelect.value,
        chat_text: chatInput.value.trim(),
        images: attachedImages.map(img => ({ filename: img.filename, data: img.data }))
      };
    }

    async function startAnalysis() {
      if (!hasApiKeyConfigured) {
        settingsModal.classList.add("active");
        return;
      }
      try {
        const res = await fetch(`/api/recordings/${encodeURIComponent(contextRecording)}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ai_act_mode: defaultAiActMode, user_name: userSpeakerName.value.trim(), ...contextPayload() })
        });
        if (!res.ok) {
          alert(t("alert.analyze_failed", { message: errorText(await res.json().catch(() => ({}))) }));
          return;
        }
        endContextStep();
        pollStatus();
      } catch (err) {
        alert(t("alert.network_error", { message: err }));
      }
    }

    laterBtn.addEventListener("click", async () => {
      try {
        const res = await fetch(`/api/recordings/${encodeURIComponent(contextRecording)}/context`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(contextPayload())
        });
        if (!res.ok) {
          alert(t("alert.context_failed", { message: errorText(await res.json().catch(() => ({}))) }));
          return;
        }
        endContextStep();
        showToast(t("toast.recording_kept"));
        fetchUnprocessed();
      } catch (err) {
        alert(t("alert.network_error", { message: err }));
      }
    });

    // "Analyze" in the list of recordings without minutes opens the same step for that recording
    function analyzeRecording(filename) {
      clearAttachments();
      showContextStep(unprocessedRecordings.find(r => r.filename === filename) || { filename });
      document.querySelector(".console-card").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    async function deleteRecording(filename) {
      if (!confirm(t("confirm.delete_recording", { name: filename }))) {
        return;
      }
      try {
        const res = await fetch(`/api/recordings/${encodeURIComponent(filename)}`, { method: "DELETE" });
        if (!res.ok) {
          alert(t("alert.delete_failed", { message: errorText(await res.json().catch(() => ({}))) }));
        }
        fetchUnprocessed();
      } catch (err) {
        alert(t("alert.network_error", { message: err }));
      }
    }

    // Audio devices: "" = Windows default, otherwise the device index
    const deviceLabel = (name) => name.replace(" [Loopback]", "");

    // Replaces only the options: the <button> in front of them shows the (truncated) selection
    function setDeviceOptions(select, options) {
      select.options.length = 0;
      options.forEach(option => select.add(option));
    }

    function fillDeviceSelect(select, devices, storageKey) {
      const saved = localStorage.getItem(storageKey) || "";
      const defaultDevice = devices.find(d => d.default);
      setDeviceOptions(select, [
        new Option(defaultDevice ? t("devices.default", { name: deviceLabel(defaultDevice.name) }) : t("devices.windows_default"), ""),
        ...devices.filter(d => !d.default).map(d => new Option(deviceLabel(d.name), String(d.index))),
      ]);
      select.value = devices.some(d => !d.default && String(d.index) === saved) ? saved : "";
    }

    async function loadDevices() {
      if (isBusy()) return;
      try {
        const res = await fetch("/api/devices");
        if (!res.ok) return;
        const data = await res.json();
        fillDeviceSelect(micSelect, data.microphones, DEVICE_STORAGE_KEYS.mic);
        fillDeviceSelect(loopbackSelect, data.loopbacks, DEVICE_STORAGE_KEYS.loopback);
      } catch (err) {
        console.error("Loading the audio devices failed:", err);
      }
    }

    // While recording/processing the selects show the devices actually in use
    function lockDeviceSelects(micDevice, loopbackDevice) {
      [[micSelect, micDevice], [loopbackSelect, loopbackDevice]].forEach(([select, name]) => {
        select.disabled = true;
        if (name && (select.options.length !== 1 || select.options[0].textContent !== deviceLabel(name))) {
          setDeviceOptions(select, [new Option(deviceLabel(name), "")]);
        }
      });
    }

    micSelect.addEventListener("change", () => localStorage.setItem(DEVICE_STORAGE_KEYS.mic, micSelect.value));
    loopbackSelect.addEventListener("change", () => localStorage.setItem(DEVICE_STORAGE_KEYS.loopback, loopbackSelect.value));

    function escapeRegExp(string) {
      return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
            if (tag === "SCRIPT" || tag === "STYLE" || tag === "MARK" || parent.closest(".transcript-toggle")) {
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
          searchMatchBadge.textContent = t("viewer.search_matches", { count });
          searchMatchBadge.className = "search-match-badge found";
          searchMatchBadge.style.display = "inline-flex";
        } else {
          searchMatchBadge.textContent = t("viewer.no_search_match");
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
      const query = (searchInput.value || "").toLowerCase().trim();
      const matches = (m, fields) => fields.some(f => (m[f] || "").toLowerCase().includes(query));
      const filtered = cachedMeetings.filter(m => !query || matches(m, ["title", "participants", "meeting_start", "created_at", "content"]));

      if (filtered.length === 0) {
        meetingsList.replaceChildren(el("p", "meetings-empty", t(cachedMeetings.length === 0 ? "sidebar.no_meetings" : "sidebar.no_results")));
        return;
      }

      meetingsList.replaceChildren(...filtered.map(m => {
        const item = el("div", "meeting-item" + (m.id === activeMeetingId ? " active" : ""));
        const body = el("div", "meeting-item-body");
        const title = el("div", "meeting-item-title", m.title || m.id);
        highlightTextInElement(title, query);
        const date = meetingDate(m, { dateStyle: "short", timeStyle: "short" });
        body.append(title, el("div", "meeting-item-date", date + (m.participants ? " • " + m.participants : "")));
        if (query && !matches(m, ["title", "participants"]) && matches(m, ["content"])) {
          body.append(el("div", "meeting-item-hint", t("sidebar.content_match")));
        }
        const deleteBtn = el("button", "delete-item-btn");
        deleteBtn.title = t("sidebar.delete_meeting");
        deleteBtn.innerHTML = TRASH_ICON;
        deleteBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          deleteMeetingPrompt(m.id, m.title || m.id);
        });
        item.append(body, deleteBtn);
        item.addEventListener("click", () => loadMeeting(m.id));
        return item;
      }));
    }

    // Status polling loop
    async function pollStatus() {
      try {
        const res = await fetch("/api/status");
        if (res.ok) {
          const data = await res.json();
          const previousStatus = currentStatus;
          currentStatus = data.status;

          if (isBusy()) {
            lockDeviceSelects(data.mic_device, data.loopback_device);
          } else if (micSelect.disabled) {
            micSelect.disabled = loopbackSelect.disabled = false;
            loadDevices();
          }
          if (previousStatus !== currentStatus && !isBusy()) {
            fetchMeetings(); // recording/analysis finished: refresh the lists
          }
          unprocessedSection.hidden = isBusy() || unprocessedList.childElementCount === 0;
          errorBanner.hidden = data.status !== "error";
          if (data.status === "error") {
            errorBanner.textContent = `⚠️ ${data.last_error || t("error.unknown")}`;
          }
          defaultAiActMode = data.default_ai_act_mode;
          renderModeWarning();

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
            statusText.innerText = t("status.recording");
            timerDisplay.innerText = formatTime(data.duration);
            recordToggleBtn.className = "record-btn stop";
            recordBtnText.innerText = t("record.stop");
            cancelRecordBtn.style.display = "flex";
            pulseRing.style.display = "block";
            processingBanner.style.display = "none";
            meetingTitleInput.disabled = true;
            meetingParticipantsInput.disabled = true;
            meetingTypeSelect.disabled = true;
            if (data.current_title && !meetingTitleInput.value) {
              meetingTitleInput.value = data.current_title;
            }
            if (data.current_participants && !participantsValue()) {
              setParticipants(data.current_participants);
            }
            if (data.current_meeting_type) {
              meetingTypeSelect.value = data.current_meeting_type;
            }
          } else if (data.status === "processing") {
            statusBadge.className = "status-badge processing";
            statusText.innerText = t("status.processing");
            recordToggleBtn.className = "record-btn";
            recordToggleBtn.disabled = true;
            recordBtnText.innerText = t("record.analyzing");
            cancelRecordBtn.style.display = "none";
            pulseRing.style.display = "none";
            processingBanner.style.display = "flex";
            processStepText.innerText = data.process_step || t("processing.default_step");
            meetingTitleInput.disabled = true;
            meetingParticipantsInput.disabled = true;
            meetingTypeSelect.disabled = true;
          } else {
            const hasError = data.status === "error";
            statusBadge.className = hasError || !data.has_api_key ? "status-badge warning" : "status-badge";
            statusText.innerText = t(hasError ? "status.error" : data.has_api_key ? "status.ready" : "status.no_api_key");
            recordToggleBtn.disabled = false;
            recordToggleBtn.className = contextRecording ? "record-btn start analyze" : "record-btn start";
            recordBtnText.innerText = t(contextRecording ? "record.analyze" : "record.start");
            cancelRecordBtn.style.display = "none";
            pulseRing.style.display = "none";
            processingBanner.style.display = "none";
            meetingTitleInput.disabled = false;
            meetingParticipantsInput.disabled = false;
            meetingTypeSelect.disabled = false;
            if (data.duration === 0) {
              timerDisplay.innerText = "00:00:00";
            }

            if (data.pending_recording && data.pending_recording !== dismissedPending && !contextRecording) {
              showContextStep({ filename: data.pending_recording });
            }

            // Open a freshly analyzed meeting once (afterwards the user's selection is kept)
            if (data.last_meeting_id && data.last_meeting_id !== lastAutoLoadedMeetingId) {
              lastAutoLoadedMeetingId = data.last_meeting_id;
              loadMeeting(data.last_meeting_id);
            }
          }

          voiceRecognitionEnabled = data.voice_recognition;
          voiceWorkers = data.voice_workers;
          voiceWorkersMax = data.voice_workers_max;
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

    // Warn before the tab is closed while recording
    window.addEventListener("beforeunload", (e) => {
      if (currentStatus === "recording") {
        e.preventDefault();
        e.returnValue = t("record.leave_warning");
      }
    });

    // Language: the saved choice, otherwise the first supported browser language
    const languageSelect = document.getElementById("languageSelect");

    function saveLanguage(language) {
      return fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ui_language: language })
      });
    }

    async function initLanguage() {
      const { current, available } = await (await fetch("/api/languages")).json();
      languageSelect.replaceChildren(...Object.entries(available).map(([code, name]) => new Option(name, code)));
      let language = current;
      if (!language) {
        language = navigator.languages.map(l => l.slice(0, 2).toLowerCase()).find(l => l in available) || "en";
        saveLanguage(language);
      }
      languageSelect.value = language;
      await i18n.load(language);
    }

    // Content the script renders itself instead of using data-i18n attributes (again after a language change)
    function renderTranslatedContent() {
      adjustUserSpeakerInputWidth();
      renderModeHint();
      updateChatStats();
      renderThumbnails();
      renderApiKeyStatus();
      fetchMeetings();
      loadDevices();
      if (activeMeetingMeta) {
        renderViewerMeta(activeMeetingMeta);
        renderVoices(activeMeetingMeta);
        renderMarkdown();
        applyViewerSearchHighlight(false);
      }
    }

    languageSelect.addEventListener("change", async () => {
      await saveLanguage(languageSelect.value);
      await i18n.load(languageSelect.value);
      renderTranslatedContent();
      pollStatus();
    });

    // Initialize
    async function pollLoop() {
      await pollStatus();
      setTimeout(pollLoop, 300);
    }

    (async () => {
      await initLanguage();
      renderTranslatedContent();
      window.addEventListener("focus", loadDevices); // e.g. a headset was plugged in while the window was in the background
      pollLoop();
      applyUrlParams();
    })();