import React, { useState, useEffect, useRef } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  ScrollView,
  FlatList,
  Modal,
  SafeAreaView,
  StatusBar,
  ActivityIndicator,
  Animated,
  Platform,
  Alert,
  Share,
  KeyboardAvoidingView
} from 'react-native';
import { Ionicons, MaterialCommunityIcons, FontAwesome5, Feather } from '@expo/vector-icons';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import * as Clipboard from 'expo-clipboard';
import * as FileSystem from 'expo-file-system';
import * as Sharing from 'expo-sharing';

// Default backend URL (points to production deployment, configurable in Settings)
const DEFAULT_API_HOST = "https://pratham-ai.vercel.app";

export default function App() {
  const [apiHost, setApiHost] = useState(DEFAULT_API_HOST);
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      content: "Hello! I am Pratham AI, created by Pratham Sinha and his team under the supervision of Akriti and Aditi Aishwaryam. How can I assist you with your project, coding, or tasks today?",
      thinkingSteps: [
        { label: "Pratham AI Engine initialized", detail: "Dual Antigravity session ready (<0.1s failover)." }
      ],
      files: []
    }
  ]);
  const [inputText, setInputText] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  const [activeAttachment, setActiveAttachment] = useState(null);
  const [expandedThinking, setExpandedThinking] = useState({});
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [conversations, setConversations] = useState([]);
  
  // Modals
  const [settingsVisible, setSettingsVisible] = useState(false);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [attachSheetVisible, setAttachSheetVisible] = useState(false);

  // Dual account statuses
  const [accountStatus, setAccountStatus] = useState({
    primary: { email: "manojkumarsinha1972@gmail.com", status: "active", is_available: true },
    secondary: { email: "pratham31sinha@gmail.com", status: "standby_ready", is_available: true },
    failover_speed: "<0.1s"
  });

  const scrollViewRef = useRef(null);

  useEffect(() => {
    fetchAccountStatus();
  }, [apiHost]);

  const fetchAccountStatus = async () => {
    try {
      const resp = await fetch(`${apiHost.replace(/\/$/, '')}/api/antigravity/accounts/status`);
      const data = await resp.json();
      if (data && data.ok) {
        setAccountStatus(data);
      }
    } catch (e) {
      // Backend status fallback
    }
  };

  const handlePickDocument = async () => {
    setAttachSheetVisible(false);
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: '*/*',
        copyToCacheDirectory: true,
      });
      if (!result.canceled && result.assets && result.assets[0]) {
        const file = result.assets[0];
        setActiveAttachment({
          uri: file.uri,
          name: file.name,
          size: file.size,
          type: file.mimeType || 'document'
        });
      }
    } catch (err) {
      Alert.alert('Error', 'Could not access documents');
    }
  };

  const handlePickImage = async (fromCamera = false) => {
    setAttachSheetVisible(false);
    try {
      let result;
      if (fromCamera) {
        const { status } = await ImagePicker.requestCameraPermissionsAsync();
        if (status !== 'granted') {
          Alert.alert('Permission needed', 'Camera permission is required');
          return;
        }
        result = await ImagePicker.launchCameraAsync({ quality: 0.8 });
      } else {
        const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (status !== 'granted') {
          Alert.alert('Permission needed', 'Gallery permission is required');
          return;
        }
        result = await ImagePicker.launchImageLibraryAsync({ quality: 0.8 });
      }

      if (!result.canceled && result.assets && result.assets[0]) {
        const asset = result.assets[0];
        const filename = asset.fileName || `photo_${Date.now()}.jpg`;
        setActiveAttachment({
          uri: asset.uri,
          name: filename,
          type: 'image',
          isImage: true
        });
      }
    } catch (err) {
      Alert.alert('Error', 'Could not pick media');
    }
  };

  const toggleThinking = (msgId) => {
    setExpandedThinking(prev => ({
      ...prev,
      [msgId]: !prev[msgId]
    }));
  };

  const copyToClipboard = async (text) => {
    await Clipboard.setStringAsync(text);
    Alert.alert('Copied', 'Code copied to clipboard');
  };

  const shareFileContent = async (filename, content) => {
    try {
      const fileUri = `${FileSystem.cacheDirectory}${filename}`;
      await FileSystem.writeAsStringAsync(fileUri, content, { encoding: FileSystem.EncodingType.UTF8 });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(fileUri);
      } else {
        Share.share({ message: content, title: filename });
      }
    } catch (err) {
      Alert.alert('Download Error', 'Could not export file');
    }
  };

  const startNewChat = () => {
    setDrawerVisible(false);
    const newId = `conv_${Date.now()}`;
    setCurrentConversationId(newId);
    setMessages([
      {
        id: 'welcome_' + newId,
        role: 'assistant',
        content: "Hello! I am Pratham AI, created by Pratham Sinha and his team under the supervision of Akriti and Aditi Aishwaryam. How can I assist you with your project, coding, or tasks today?",
        thinkingSteps: [
          { label: "Pratham AI Engine ready", detail: "Dual Antigravity session active (<0.1s auto-failover)." }
        ],
        files: []
      }
    ]);
  };

  const sendMessage = async () => {
    const text = inputText.trim();
    if ((!text && !activeAttachment) || isGenerating) return;

    const userMsgId = `user_${Date.now()}`;
    let outgoingContent = text;
    let attachedMeta = null;

    if (activeAttachment) {
      attachedMeta = { ...activeAttachment };
      if (activeAttachment.isImage) {
        outgoingContent = `[Attached Image for Vision Analysis: ${activeAttachment.name}]\n` + outgoingContent;
      } else {
        outgoingContent = `[Attached File: ${activeAttachment.name}]\n` + outgoingContent;
      }
    }

    if (!webSearchEnabled) {
      outgoingContent = "[[NO_WEB_SEARCH]]" + outgoingContent;
    }

    const newUserMessage = {
      id: userMsgId,
      role: 'user',
      content: text || `Sent attachment: ${activeAttachment?.name}`,
      attachment: attachedMeta
    };

    const assistantMsgId = `asst_${Date.now()}`;
    const newAssistantMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      thinkingSteps: [],
      files: []
    };

    setMessages(prev => [...prev, newUserMessage, newAssistantMessage]);
    setInputText('');
    setActiveAttachment(null);
    setIsGenerating(true);
    setExpandedThinking(prev => ({ ...prev, [assistantMsgId]: true }));

    // Auto scroll down
    setTimeout(() => scrollViewRef.current?.scrollToEnd({ animated: true }), 100);

    try {
      const endpoint = `${apiHost.replace(/\/$/, '')}/api/chat-stream`;
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream'
        },
        body: JSON.stringify({
          message: outgoingContent,
          conversation_id: currentConversationId || undefined
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader?.();
      if (!reader) {
        // Fallback for standard react native fetch
        const rawText = await response.text();
        const lines = rawText.split('\n');
        let fullText = '';
        const steps = [];
        const filesList = [];

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.substring(6));
              if (data.type === 'token') {
                fullText += data.text;
              } else if (data.type === 'agent_step') {
                steps.push({ label: data.label, detail: data.detail });
              } else if (data.type === 'file_ready' || data.type === 'activity_created') {
                filesList.push({ filename: data.filename, size: data.size_bytes });
              }
            } catch (e) {}
          }
        }

        setMessages(prev => prev.map(m => {
          if (m.id === assistantMsgId) {
            return {
              ...m,
              content: fullText || "Deliverable completed.",
              thinkingSteps: steps.length > 0 ? steps : [{ label: "Analyzing & executing", detail: "Synthesizing response." }],
              files: filesList
            };
          }
          return m;
        }));
      } else {
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';
        const steps = [];
        const filesList = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.substring(6));
                if (data.type === 'token') {
                  fullText += data.text;
                  setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: fullText } : m));
                } else if (data.type === 'agent_step') {
                  steps.push({ label: data.label, detail: data.detail });
                  setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, thinkingSteps: [...steps] } : m));
                } else if (data.type === 'file_ready' || data.type === 'activity_created') {
                  filesList.push({ filename: data.filename, size: data.size_bytes });
                  setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, files: [...filesList] } : m));
                }
              } catch (e) {}
            }
          }
        }
      }
    } catch (err) {
      setMessages(prev => prev.map(m => {
        if (m.id === assistantMsgId) {
          return {
            ...m,
            content: (m.content || '') + `\n\n*(Error connecting to Pratham AI server: ${err.message}. Please verify settings or connection.)*`
          };
        }
        return m;
      }));
    } finally {
      setIsGenerating(false);
      setTimeout(() => scrollViewRef.current?.scrollToEnd({ animated: true }), 100);
    }
  };

  // Helper parser for markdown code blocks
  const renderMessageContent = (content) => {
    if (!content) return null;
    const parts = [];
    const codeBlockRegex = /```([a-zA-Z0-9_\-\:]*)\n([\s\S]*?)```/g;
    let lastIndex = 0;
    let match;

    while ((match = codeBlockRegex.exec(content)) !== null) {
      if (match.index > lastIndex) {
        parts.push({
          type: 'text',
          text: content.substring(lastIndex, match.index)
        });
      }
      const lang = match[1] || 'code';
      const code = match[2];
      parts.push({
        type: 'code',
        lang: lang,
        code: code
      });
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < content.length) {
      parts.push({
        type: 'text',
        text: content.substring(lastIndex)
      });
    }

    return (
      <View>
        {parts.map((p, idx) => {
          if (p.type === 'code') {
            const isFile = p.lang.startsWith('createfile:') || p.lang.startsWith('editfile:');
            const cleanTitle = isFile ? p.lang.replace(/^(createfile:|editfile:)/, '') : p.lang.toUpperCase();
            return (
              <View key={idx} style={styles.codeContainer}>
                <View style={styles.codeHeader}>
                  <Text style={styles.codeLang}>{cleanTitle || 'CODE'}</Text>
                  <View style={{ flexDirection: 'row', gap: 10 }}>
                    <TouchableOpacity onPress={() => copyToClipboard(p.code)} style={styles.codeActionBtn}>
                      <Feather name="copy" size={13} color="#94a3b8" />
                      <Text style={styles.codeActionTxt}>Copy</Text>
                    </TouchableOpacity>
                    {isFile && (
                      <TouchableOpacity onPress={() => shareFileContent(cleanTitle, p.code)} style={styles.codeActionBtn}>
                        <Feather name="download" size={13} color="#3b82f6" />
                        <Text style={[styles.codeActionTxt, { color: '#3b82f6' }]}>Export</Text>
                      </TouchableOpacity>
                    )}
                  </View>
                </View>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.codeScroll}>
                  <Text style={styles.codeText}>{p.code}</Text>
                </ScrollView>
              </View>
            );
          }
          return (
            <Text key={idx} style={styles.messageText}>
              {p.text}
            </Text>
          );
        })}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#090d16" />

      {/* App Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => setDrawerVisible(true)} style={styles.headerIconBtn}>
          <Feather name="menu" size={22} color="#f8fafc" />
        </TouchableOpacity>

        <View style={styles.headerTitleWrap}>
          <View style={styles.logoBadge}>
            <Text style={styles.logoBadgeTxt}>P</Text>
          </View>
          <Text style={styles.headerTitle}>Pratham AI</Text>
          <View style={styles.statusDot} />
        </View>

        <View style={styles.headerRight}>
          <TouchableOpacity onPress={startNewChat} style={styles.headerIconBtn}>
            <Feather name="edit" size={19} color="#94a3b8" />
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setSettingsVisible(true)} style={styles.headerIconBtn}>
            <Feather name="settings" size={19} color="#94a3b8" />
          </TouchableOpacity>
        </View>
      </View>

      {/* Dual Account Fast Status Ribbon */}
      <View style={styles.statusRibbon}>
        <View style={styles.statusRibbonLeft}>
          <View style={[styles.microDot, { backgroundColor: '#10b981' }]} />
          <Text style={styles.statusRibbonTxt}>Dual Account Active</Text>
        </View>
        <Text style={styles.statusRibbonFailover}>Auto-Failover &lt;0.1s</Text>
      </View>

      {/* Message Chat List */}
      <ScrollView
        ref={scrollViewRef}
        style={styles.chatArea}
        contentContainerStyle={styles.chatContent}
        keyboardShouldPersistTaps="handled"
      >
        {messages.map((item) => {
          const isUser = item.role === 'user';
          const hasThinking = item.thinkingSteps && item.thinkingSteps.length > 0;
          const isThinkingOpen = !!expandedThinking[item.id];

          return (
            <View key={item.id} style={[styles.msgRow, isUser ? styles.msgRowUser : styles.msgRowAsst]}>
              {!isUser && (
                <View style={styles.asstAvatar}>
                  <Text style={styles.asstAvatarTxt}>P</Text>
                </View>
              )}

              <View style={[styles.msgBubble, isUser ? styles.msgBubbleUser : styles.msgBubbleAsst]}>
                {/* User Attachment Chip */}
                {isUser && item.attachment && (
                  <View style={styles.userAttachChip}>
                    <Feather name={item.attachment.isImage ? "image" : "paperclip"} size={13} color="#93c5fd" />
                    <Text style={styles.userAttachChipTxt} numberOfLines={1}>
                      {item.attachment.name}
                    </Text>
                  </View>
                )}

                {/* Assistant Collapsible Thinking Box */}
                {!isUser && hasThinking && (
                  <View style={styles.thinkingBox}>
                    <TouchableOpacity
                      onPress={() => toggleThinking(item.id)}
                      style={styles.thinkingHeader}
                    >
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                        <MaterialCommunityIcons name="brain" size={16} color="#818cf8" />
                        <Text style={styles.thinkingTitle}>
                          Thought process ({item.thinkingSteps.length} step{item.thinkingSteps.length > 1 ? 's' : ''})
                        </Text>
                      </View>
                      <Feather name={isThinkingOpen ? "chevron-up" : "chevron-down"} size={16} color="#94a3b8" />
                    </TouchableOpacity>

                    {isThinkingOpen && (
                      <View style={styles.thinkingBody}>
                        {item.thinkingSteps.map((step, sIdx) => (
                          <View key={sIdx} style={styles.thinkingStepRow}>
                            <View style={styles.stepDot} />
                            <View style={{ flex: 1 }}>
                              <Text style={styles.stepLabel}>{step.label}</Text>
                              {step.detail ? <Text style={styles.stepDetail}>{step.detail}</Text> : null}
                            </View>
                          </View>
                        ))}
                      </View>
                    )}
                  </View>
                )}

                {/* Message Body */}
                {renderMessageContent(item.content)}

                {/* Generated Files Deliverable Cards */}
                {!isUser && item.files && item.files.length > 0 && (
                  <View style={styles.deliverablesWrap}>
                    {item.files.map((f, fIdx) => (
                      <View key={fIdx} style={styles.fileDeliverableCard}>
                        <View style={styles.fileCardIcon}>
                          <Feather name={f.filename.endsWith('.zip') ? "archive" : "file-code"} size={18} color="#3b82f6" />
                        </View>
                        <View style={{ flex: 1, minWidth: 0 }}>
                          <Text style={styles.fileCardName} numberOfLines={1}>{f.filename}</Text>
                          <Text style={styles.fileCardMeta}>Deliverable ready</Text>
                        </View>
                        <TouchableOpacity
                          onPress={() => shareFileContent(f.filename, item.content)}
                          style={styles.fileCardDownloadBtn}
                        >
                          <Feather name="download" size={15} color="#fff" />
                        </TouchableOpacity>
                      </View>
                    ))}
                  </View>
                )}
              </View>
            </View>
          );
        })}

        {isGenerating && (
          <View style={styles.typingIndicatorRow}>
            <ActivityIndicator size="small" color="#3b82f6" />
            <Text style={styles.typingIndicatorTxt}>Pratham AI is synthesizing response...</Text>
          </View>
        )}
      </ScrollView>

      {/* Composer Bottom Bar */}
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.composerWrapper}>
          {/* Active File Attachment Preview Chip */}
          {activeAttachment && (
            <View style={styles.composerAttachChip}>
              <Feather name={activeAttachment.isImage ? "image" : "paperclip"} size={14} color="#60a5fa" />
              <Text style={styles.composerAttachChipTxt} numberOfLines={1}>
                {activeAttachment.name}
              </Text>
              <TouchableOpacity onPress={() => setActiveAttachment(null)}>
                <Feather name="x" size={15} color="#94a3b8" />
              </TouchableOpacity>
            </View>
          )}

          {/* Quick Toolbar */}
          <View style={styles.composerToolbar}>
            <TouchableOpacity
              onPress={() => setWebSearchEnabled(!webSearchEnabled)}
              style={[styles.webSearchToggle, webSearchEnabled && styles.webSearchToggleActive]}
            >
              <Feather name="globe" size={13} color={webSearchEnabled ? "#60a5fa" : "#64748b"} />
              <Text style={[styles.webSearchToggleTxt, webSearchEnabled && styles.webSearchToggleTxtActive]}>
                Web Search: {webSearchEnabled ? 'ON' : 'OFF'}
              </Text>
            </TouchableOpacity>
          </View>

          {/* Input & Action Buttons */}
          <View style={styles.composerInputRow}>
            <TouchableOpacity
              onPress={() => setAttachSheetVisible(true)}
              style={styles.attachBtn}
            >
              <Feather name="plus" size={20} color="#94a3b8" />
            </TouchableOpacity>

            <TextInput
              style={styles.composerInput}
              placeholder="Ask Pratham AI anything..."
              placeholderTextColor="#64748b"
              value={inputText}
              onChangeText={setInputText}
              multiline
              maxLength={15000}
            />

            <TouchableOpacity
              onPress={sendMessage}
              disabled={(!inputText.trim() && !activeAttachment) || isGenerating}
              style={[
                styles.sendBtn,
                ((inputText.trim() || activeAttachment) && !isGenerating) && styles.sendBtnActive
              ]}
            >
              {isGenerating ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Feather name="arrow-up" size={18} color="#fff" />
              )}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>

      {/* Attachment Action Sheet Modal */}
      <Modal
        visible={attachSheetVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setAttachSheetVisible(false)}
      >
        <TouchableOpacity
          style={styles.modalBackdrop}
          activeOpacity={1}
          onPress={() => setAttachSheetVisible(false)}
        >
          <View style={styles.attachSheetContainer}>
            <Text style={styles.attachSheetTitle}>Attach to Pratham AI</Text>
            <View style={styles.attachGrid}>
              <TouchableOpacity onPress={() => handlePickImage(true)} style={styles.attachGridItem}>
                <View style={[styles.attachIconWrap, { backgroundColor: '#1e3a8a' }]}>
                  <Feather name="camera" size={22} color="#60a5fa" />
                </View>
                <Text style={styles.attachGridLabel}>Camera</Text>
              </TouchableOpacity>

              <TouchableOpacity onPress={() => handlePickImage(false)} style={styles.attachGridItem}>
                <View style={[styles.attachIconWrap, { backgroundColor: '#065f46' }]}>
                  <Feather name="image" size={22} color="#34d399" />
                </View>
                <Text style={styles.attachGridLabel}>Gallery</Text>
              </TouchableOpacity>

              <TouchableOpacity onPress={handlePickDocument} style={styles.attachGridItem}>
                <View style={[styles.attachIconWrap, { backgroundColor: '#4c1d95' }]}>
                  <Feather name="file-text" size={22} color="#a78bfa" />
                </View>
                <Text style={styles.attachGridLabel}>Document</Text>
              </TouchableOpacity>
            </View>
          </View>
        </TouchableOpacity>
      </Modal>

      {/* Settings Modal */}
      <Modal
        visible={settingsVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setSettingsVisible(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.settingsModalCard}>
            <View style={styles.settingsModalHeader}>
              <Text style={styles.settingsModalTitle}>Settings & Accounts</Text>
              <TouchableOpacity onPress={() => setSettingsVisible(false)}>
                <Feather name="x" size={20} color="#94a3b8" />
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.settingsScroll}>
              {/* Dual Account Showcase */}
              <Text style={styles.settingsSectionTitle}>ANTIGRAVITY ACCOUNTS</Text>

              <View style={styles.accountCard}>
                <View style={styles.accountCardRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.accountRoleTxt}>Primary Account</Text>
                    <Text style={styles.accountEmailTxt}>manojkumarsinha1972@gmail.com</Text>
                  </View>
                  <View style={styles.accountBadgeActive}>
                    <Text style={styles.accountBadgeActiveTxt}>Primary · Active</Text>
                  </View>
                </View>
              </View>

              <View style={styles.accountCard}>
                <View style={styles.accountCardRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.accountRoleTxt}>Failover Account</Text>
                    <Text style={styles.accountEmailTxt}>pratham31sinha@gmail.com</Text>
                  </View>
                  <View style={styles.accountBadgeStandby}>
                    <Text style={styles.accountBadgeStandbyTxt}>Standby &lt;0.1s</Text>
                  </View>
                </View>
                <Text style={styles.accountNoteTxt}>
                  Warm standby session ready to failover instantly if Primary quota is reached.
                </Text>
              </View>

              {/* Server Host */}
              <Text style={[styles.settingsSectionTitle, { marginTop: 16 }]}>SERVER CONTEXT</Text>
              <View style={styles.settingsInputGroup}>
                <Text style={styles.inputLabel}>Backend API Endpoint</Text>
                <TextInput
                  style={styles.settingsTextInput}
                  value={apiHost}
                  onChangeText={setApiHost}
                  placeholder="https://your-vercel-domain.app"
                  placeholderTextColor="#64748b"
                />
              </View>

              {/* Creator info */}
              <Text style={[styles.settingsSectionTitle, { marginTop: 16 }]}>ABOUT PRATHAM AI</Text>
              <View style={styles.infoRow}>
                <Text style={styles.infoLabel}>Product & Engineering</Text>
                <Text style={styles.infoValue}>Pratham Sinha & team</Text>
              </View>
              <View style={styles.infoRow}>
                <Text style={styles.infoLabel}>Supervision</Text>
                <Text style={styles.infoValue}>Akriti & Aditi Aishwaryam</Text>
              </View>
              <View style={styles.infoRow}>
                <Text style={styles.infoLabel}>Architecture</Text>
                <Text style={styles.infoValue}>Dual Antigravity Engine</Text>
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Drawer / History Modal */}
      <Modal
        visible={drawerVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setDrawerVisible(false)}
      >
        <TouchableOpacity
          style={styles.modalBackdrop}
          activeOpacity={1}
          onPress={() => setDrawerVisible(false)}
        >
          <View style={styles.drawerCard}>
            <View style={styles.drawerHeader}>
              <Text style={styles.drawerTitle}>Conversations</Text>
              <TouchableOpacity onPress={startNewChat} style={styles.drawerNewBtn}>
                <Feather name="plus" size={16} color="#fff" />
                <Text style={styles.drawerNewBtnTxt}>New</Text>
              </TouchableOpacity>
            </View>

            <View style={styles.drawerList}>
              <TouchableOpacity
                onPress={() => setDrawerVisible(false)}
                style={styles.drawerItemActive}
              >
                <Feather name="message-square" size={16} color="#60a5fa" />
                <Text style={styles.drawerItemTxtActive} numberOfLines={1}>Current Chat</Text>
              </TouchableOpacity>
            </View>
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#090d16',
  },
  header: {
    height: 56,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
    backgroundColor: '#090d16',
  },
  headerIconBtn: {
    padding: 6,
  },
  headerTitleWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  logoBadge: {
    width: 24,
    height: 24,
    borderRadius: 6,
    backgroundColor: '#2563eb',
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoBadgeTxt: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#f8fafc',
    letterSpacing: 0.3,
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: '#10b981',
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  statusRibbon: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 5,
    backgroundColor: '#0f172a',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  statusRibbonLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  microDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  statusRibbonTxt: {
    fontSize: 11,
    fontWeight: '600',
    color: '#94a3b8',
  },
  statusRibbonFailover: {
    fontSize: 11,
    color: '#60a5fa',
    fontWeight: '600',
  },
  chatArea: {
    flex: 1,
  },
  chatContent: {
    paddingHorizontal: 14,
    paddingTop: 14,
    paddingBottom: 24,
  },
  msgRow: {
    flexDirection: 'row',
    marginBottom: 16,
  },
  msgRowUser: {
    justifyContent: 'flex-end',
  },
  msgRowAsst: {
    justifyContent: 'flex-start',
    gap: 10,
  },
  asstAvatar: {
    width: 28,
    height: 28,
    borderRadius: 8,
    backgroundColor: '#1d4ed8',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  asstAvatarTxt: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 13,
  },
  msgBubble: {
    maxWidth: '85%',
    borderRadius: 14,
    padding: 12,
  },
  msgBubbleUser: {
    backgroundColor: '#2563eb',
    borderBottomRightRadius: 3,
  },
  msgBubbleAsst: {
    backgroundColor: '#131b2e',
    borderTopLeftRadius: 3,
    borderWidth: 1,
    borderColor: '#1e293b',
    flex: 1,
  },
  messageText: {
    fontSize: 14,
    lineHeight: 21,
    color: '#f1f5f9',
  },
  userAttachChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: 'rgba(0,0,0,0.2)',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    marginBottom: 6,
  },
  userAttachChipTxt: {
    fontSize: 12,
    color: '#93c5fd',
    fontWeight: '500',
  },
  thinkingBox: {
    backgroundColor: '#0f172a',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#1e293b',
    marginBottom: 10,
    overflow: 'hidden',
  },
  thinkingHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  thinkingTitle: {
    fontSize: 12,
    fontWeight: '600',
    color: '#c7d2fe',
  },
  thinkingBody: {
    paddingHorizontal: 10,
    paddingBottom: 8,
    borderTopWidth: 1,
    borderTopColor: '#1e293b',
    paddingTop: 6,
  },
  thinkingStepRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    marginBottom: 6,
  },
  stepDot: {
    width: 5,
    height: 5,
    borderRadius: 3,
    backgroundColor: '#818cf8',
    marginTop: 5,
  },
  stepLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#e2e8f0',
  },
  stepDetail: {
    fontSize: 11,
    color: '#94a3b8',
    marginTop: 1,
  },
  codeContainer: {
    backgroundColor: '#090d16',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#1e293b',
    marginVertical: 8,
    overflow: 'hidden',
  },
  codeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: '#0f172a',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  codeLang: {
    fontSize: 11,
    fontWeight: '700',
    color: '#60a5fa',
  },
  codeActionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  codeActionTxt: {
    fontSize: 11,
    color: '#94a3b8',
  },
  codeScroll: {
    padding: 10,
  },
  codeText: {
    fontFamily: Platform.OS === 'ios' ? 'Courier' : 'monospace',
    fontSize: 12,
    color: '#38bdf8',
    lineHeight: 18,
  },
  deliverablesWrap: {
    marginTop: 10,
    gap: 8,
  },
  fileDeliverableCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#0f172a',
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#2563eb33',
  },
  fileCardIcon: {
    width: 32,
    height: 32,
    borderRadius: 6,
    backgroundColor: '#1e3a8a33',
    alignItems: 'center',
    justifyContent: 'center',
  },
  fileCardName: {
    fontSize: 13,
    fontWeight: '600',
    color: '#f8fafc',
  },
  fileCardMeta: {
    fontSize: 11,
    color: '#94a3b8',
  },
  fileCardDownloadBtn: {
    width: 30,
    height: 30,
    borderRadius: 6,
    backgroundColor: '#2563eb',
    alignItems: 'center',
    justifyContent: 'center',
  },
  typingIndicatorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginVertical: 10,
    paddingLeft: 38,
  },
  typingIndicatorTxt: {
    fontSize: 12,
    color: '#94a3b8',
    fontStyle: 'italic',
  },
  composerWrapper: {
    backgroundColor: '#0f172a',
    borderTopWidth: 1,
    borderTopColor: '#1e293b',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  composerAttachChip: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 6,
    backgroundColor: '#1e293b',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 6,
    marginBottom: 6,
  },
  composerAttachChipTxt: {
    fontSize: 12,
    color: '#f1f5f9',
    maxWidth: 200,
  },
  composerToolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  webSearchToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: '#1e293b',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
  },
  webSearchToggleActive: {
    backgroundColor: '#1e3a8a44',
    borderWidth: 1,
    borderColor: '#3b82f6',
  },
  webSearchToggleTxt: {
    fontSize: 11,
    color: '#64748b',
    fontWeight: '600',
  },
  webSearchToggleTxtActive: {
    color: '#60a5fa',
  },
  composerInputRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
  },
  attachBtn: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: '#1e293b',
    alignItems: 'center',
    justifyContent: 'center',
  },
  composerInput: {
    flex: 1,
    backgroundColor: '#1e293b',
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingTop: 8,
    paddingBottom: 8,
    fontSize: 14,
    color: '#f8fafc',
    maxHeight: 120,
  },
  sendBtn: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: '#334155',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnActive: {
    backgroundColor: '#2563eb',
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.65)',
    justifyContent: 'flex-end',
  },
  attachSheetContainer: {
    backgroundColor: '#0f172a',
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    padding: 20,
    borderTopWidth: 1,
    borderTopColor: '#1e293b',
  },
  attachSheetTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: '#f8fafc',
    marginBottom: 16,
    textAlign: 'center',
  },
  attachGrid: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  attachGridItem: {
    alignItems: 'center',
    gap: 8,
  },
  attachIconWrap: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
  },
  attachGridLabel: {
    fontSize: 12,
    color: '#cbd5e1',
    fontWeight: '500',
  },
  settingsModalCard: {
    backgroundColor: '#0f172a',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: '85%',
    padding: 18,
  },
  settingsModalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  settingsModalTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: '#f8fafc',
  },
  settingsScroll: {
    marginTop: 14,
  },
  settingsSectionTitle: {
    fontSize: 11,
    fontWeight: '700',
    color: '#64748b',
    letterSpacing: 0.8,
    marginBottom: 8,
  },
  accountCard: {
    backgroundColor: '#131b2e',
    borderRadius: 10,
    padding: 12,
    borderWidth: 1,
    borderColor: '#1e293b',
    marginBottom: 10,
  },
  accountCardRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  accountRoleTxt: {
    fontSize: 13,
    fontWeight: '700',
    color: '#f8fafc',
  },
  accountEmailTxt: {
    fontSize: 12,
    fontFamily: Platform.OS === 'ios' ? 'Courier' : 'monospace',
    color: '#60a5fa',
    marginTop: 2,
  },
  accountBadgeActive: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
  },
  accountBadgeActiveTxt: {
    color: '#34d399',
    fontSize: 11,
    fontWeight: '700',
  },
  accountBadgeStandby: {
    backgroundColor: 'rgba(59, 130, 246, 0.15)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
  },
  accountBadgeStandbyTxt: {
    color: '#60a5fa',
    fontSize: 11,
    fontWeight: '700',
  },
  accountNoteTxt: {
    fontSize: 11,
    color: '#94a3b8',
    marginTop: 8,
    lineHeight: 16,
  },
  settingsInputGroup: {
    backgroundColor: '#131b2e',
    borderRadius: 10,
    padding: 12,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  inputLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#cbd5e1',
    marginBottom: 6,
  },
  settingsTextInput: {
    backgroundColor: '#090d16',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    color: '#f8fafc',
    fontSize: 13,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  infoLabel: {
    fontSize: 13,
    color: '#94a3b8',
  },
  infoValue: {
    fontSize: 13,
    fontWeight: '600',
    color: '#f8fafc',
  },
  drawerCard: {
    backgroundColor: '#0f172a',
    width: '75%',
    height: '100%',
    padding: 16,
    borderRightWidth: 1,
    borderRightColor: '#1e293b',
  },
  drawerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  drawerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#f8fafc',
  },
  drawerNewBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#2563eb',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 6,
  },
  drawerNewBtnTxt: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '600',
  },
  drawerList: {
    marginTop: 14,
  },
  drawerItemActive: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#1e3a8a33',
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#2563eb44',
  },
  drawerItemTxtActive: {
    fontSize: 13,
    fontWeight: '600',
    color: '#93c5fd',
  },
});
