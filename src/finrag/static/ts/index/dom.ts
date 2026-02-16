const byId = (id: string): any => document.getElementById(id);

export const els = {
  healthPill: byId('healthPill'),
  newChatBtn: byId('newChatBtn'),
  reloadHistoryBtn: byId('reloadHistoryBtn'),
  exportHistoryBtn: byId('exportHistoryBtn'),
  clearHistoryBtn: byId('clearHistoryBtn'),
  historyCount: byId('historyCount'),
  historyPath: byId('historyPath'),
  historyFilter: byId('historyFilter'),
  historyList: byId('historyList'),
  activeEntryPill: byId('activeEntryPill'),

  queryForm: byId('queryForm'),
  question: byId('question'),
  genMode: byId('genMode'),
  genModeHelp: byId('genModeHelp'),
  enableRefine: byId('enableRefine'),
  topKRetrieve: byId('topKRetrieve'),
  topKRerank: byId('topKRerank'),
  draftMaxTokens: byId('draftMaxTokens'),
  finalMaxTokens: byId('finalMaxTokens'),
  briefMaxTokens: byId('briefMaxTokens'),
  answeringEffort: byId('answeringEffort'),
  queryBtn: byId('queryBtn'),
  stopBtn: byId('stopBtn'),
  queryStatus: byId('queryStatus'),

  answerBlock: byId('answerBlock'),
  answerSplit: byId('answerSplit'),
  answerPane: byId('answerPane'),
  chunksPane: byId('chunksPane'),
  answerSplitter: byId('answerSplitter'),
  requestIdPill: byId('requestIdPill'),
  progressSummaryPill: byId('progressSummaryPill'),
  progressPipeline: byId('progressPipeline'),
  progressLogDetails: byId('progressLogDetails'),
  progressLog: byId('progressLog'),
  draftDetails: byId('draftDetails'),
  draftStatePill: byId('draftStatePill'),
  draftAnswer: byId('draftAnswer'),
  toolResultsDetails: byId('toolResultsDetails'),
  toolResultsCountPill: byId('toolResultsCountPill'),
  toolResultsStatus: byId('toolResultsStatus'),
  toolResults: byId('toolResults'),
  briefsDetails: byId('briefsDetails'),
  briefsCountPill: byId('briefsCountPill'),
  briefsStatus: byId('briefsStatus'),
  briefsContainer: byId('briefsContainer'),
  finalAnswer: byId('finalAnswer'),
  retrievedDetails: byId('retrievedDetails'),
  retrievedCountPill: byId('retrievedCountPill'),
  retrievedChunks: byId('retrievedChunks'),
  chunks: byId('chunks'),
  chunkCountPill: byId('chunkCountPill'),

  copyAnswerBtn: byId('copyAnswerBtn'),
  copyDebugBtn: byId('copyDebugBtn'),

  sourceViewerDetails: byId('sourceViewerDetails'),
  sourceCountPill: byId('sourceCountPill'),
  sourceModePill: byId('sourceModePill'),
  sourceSelect: byId('sourceSelect'),
  sourceReloadBtn: byId('sourceReloadBtn'),
  sourceToggleModeBtn: byId('sourceToggleModeBtn'),
  sourceStatus: byId('sourceStatus'),
  sourceContent: byId('sourceContent'),
  sourceMeta: byId('sourceMeta'),

  qaSplit: byId('qaSplit'),
  qaSplitter: byId('qaSplitter'),
  qaSources: byId('qaSources'),

  ingestedDetails: byId('ingestedDetails'),
  ingestTicker: byId('ingestTicker'),
  ingestPerCompany: byId('ingestPerCompany'),
  ingestBtn: byId('ingestBtn'),
  ingestJobPill: byId('ingestJobPill'),
  ingestJobStatus: byId('ingestJobStatus'),
  ingestedCountPill: byId('ingestedCountPill'),
  ingestedStatus: byId('ingestedStatus'),
  ingestedFilter: byId('ingestedFilter'),
  ingestedList: byId('ingestedList'),
};

export const LS_HISTORY = 'finrag_history_v1';
export const LS_SETTINGS = 'finrag_settings_v1';
export const LS_UI = 'finrag_ui_v1';

export const DEFAULT_SOURCES_PANE_WIDTH_PX = 460;
export const DEFAULT_ANSWER_PANE_PCT = 85;

export const STEP_ORDER = ['retrieve', 'rerank', 'draft', 'briefs', 'final'];
