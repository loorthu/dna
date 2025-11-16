import React, { useEffect } from 'react';
import GoogleMeetPanel from './Panels/GoogleMeetPanel';
import ShotGridPanel from './Panels/ShotGridPanel';
import UploadPanel from './Panels/UploadPanel';
import ExportPanel from './Panels/ExportPanel';
import SettingsPanel from './Panels/SettingsPanel';
import ShotTable from './ShotTable';
import FloatingControls from './FloatingControls';
import AddShotControls from './AddShotControls';

function AppLayout({
  // Configuration
  config,
  configLoaded,
  enabledLLMs,
  availablePromptTypes,
  
  // State
  rows,
  currentIndex,
  setCurrentIndex,
  pinnedIndex,
  setPinnedIndex,
  activeTab,
  setActiveTab,
  activeTopTab,
  setActiveTopTab,
  promptTypeSelection,
  setPromptTypeSelection,
  
  // Google Meet
  meetId,
  setMeetId,
  onSubmit,
  onExitBot,
  botIsActive,
  submitting,
  waitingForActive,
  
  // Transcription
  isReceivingTranscripts,
  joinedMeetId,
  onTranscriptToggle,
  shotSegments,
  status,
  
  // Settings
  includeSpeakerLabels,
  setIncludeSpeakerLabels,
  autoGenerateSummary,
  setAutoGenerateSummary,
  autoSummaryLLM,
  setAutoSummaryLLM,
  
  // Utility functions
  updateCell,
  setRows,
  selectedProjectId
}) {
  // Separate state for import sub-tabs vs shot table row tabs
  const [importSubTab, setImportSubTab] = React.useState(config.shotgrid_enabled ? 'shotgrid' : 'upload');
  const [shotTableRowTabs, setShotTableRowTabs] = React.useState({});
  // Initialize tabs on component mount
  useEffect(() => {
    // Always set default top tab to import on mount
    setActiveTopTab('import');
    
    // Set default import sub-tab based on config
    if (config.shotgrid_enabled) {
      setImportSubTab('shotgrid');
    } else {
      setImportSubTab('upload');
    }
  }, [config.shotgrid_enabled, setActiveTopTab]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1 className="app-title">Dailies Note Assistant (v2)</h1>
        <p className="app-subtitle">AI Assistant to join a Google meet based review session to capture the audio transcription and generate summaries for specific shots as guided by the user</p>
      </header>

      <main className="app-main">
        <section className="panel" style={{ height: '295px', minWidth: '600px' }}>
          {/* Tab Navigation */}
          <div style={{ display: 'flex', borderBottom: '1px solid #2c323c', marginBottom: '16px' }}>
            <button
              type="button"
              className={`tab-button ${activeTopTab === 'import' ? 'active' : ''}`}
              onClick={() => setActiveTopTab('import')}
            >
              Import
            </button>
            <button
              type="button"
              className={`tab-button ${activeTopTab === 'panel' ? 'active' : ''}`}
              onClick={() => setActiveTopTab('panel')}
            >
              Google Meet
            </button>
            <button
              type="button"
              className={`tab-button ${activeTopTab === 'export' ? 'active' : ''}`}
              onClick={() => setActiveTopTab('export')}
            >
              Export
            </button>
            <button
              type="button"
              className={`tab-button ${activeTopTab === 'settings' ? 'active' : ''}`}
              onClick={() => setActiveTopTab('settings')}
            >
              Settings
            </button>
          </div>

          {/* Tab Content */}
          <div style={{ height: '255px' }}>
            {activeTopTab === 'import' && (
              <div style={{ height: '100%' }}>
                {/* Import Sub-tabs */}
                <div style={{ display: 'flex', marginBottom: '12px' }}>
                  {config.shotgrid_enabled && (
                    <button
                      type="button"
                      className={`tab-button ${importSubTab === 'shotgrid' ? 'active' : ''}`}
                      onClick={() => setImportSubTab('shotgrid')}
                      style={{ fontSize: '14px', padding: '6px 12px' }}
                    >
                      ShotGrid
                    </button>
                  )}
                  <button
                    type="button"
                    className={`tab-button ${importSubTab === 'upload' ? 'active' : ''}`}
                    onClick={() => setImportSubTab('upload')}
                    style={{ fontSize: '14px', padding: '6px 12px' }}
                  >
                    Upload Playlist
                  </button>
                </div>
                
                {/* Import Content */}
                <div style={{ height: 'calc(100% - 40px)' }}>
                  {importSubTab === 'shotgrid' && config.shotgrid_enabled && (
                    <ShotGridPanel
                      config={config}
                      configLoaded={configLoaded}
                      setRows={setRows}
                      setCurrentIndex={setCurrentIndex}
                    />
                  )}
                  
                  {importSubTab === 'upload' && (
                    <UploadPanel 
                      setRows={setRows} 
                      setCurrentIndex={setCurrentIndex} 
                    />
                  )}
                </div>
              </div>
            )}

            {activeTopTab === 'panel' && (
              <GoogleMeetPanel
                meetId={meetId}
                setMeetId={setMeetId}
                onSubmit={onSubmit}
                onExitBot={onExitBot}
                botIsActive={botIsActive}
                submitting={submitting}
                waitingForActive={waitingForActive}
              />
            )}

            {activeTopTab === 'export' && (
              <ExportPanel 
                rows={rows} 
                shotSegments={shotSegments} 
              />
            )}

            {activeTopTab === 'settings' && (
              <SettingsPanel
                includeSpeakerLabels={includeSpeakerLabels}
                setIncludeSpeakerLabels={setIncludeSpeakerLabels}
                autoGenerateSummary={autoGenerateSummary}
                setAutoGenerateSummary={setAutoGenerateSummary}
                autoSummaryLLM={autoSummaryLLM}
                setAutoSummaryLLM={setAutoSummaryLLM}
                enabledLLMs={enabledLLMs}
              />
            )}
          </div>
        </section>

        <section className="panel full-span">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h2 className="panel-title" style={{ margin: 0 }}>Shot Notes</h2>
          </div>
          
          <ShotTable
            rows={rows}
            currentIndex={currentIndex}
            setCurrentIndex={setCurrentIndex}
            pinnedIndex={pinnedIndex}
            setPinnedIndex={setPinnedIndex}
            activeTab={shotTableRowTabs}
            setActiveTab={setShotTableRowTabs}
            enabledLLMs={enabledLLMs}
            availablePromptTypes={availablePromptTypes}
            promptTypeSelection={promptTypeSelection}
            setPromptTypeSelection={setPromptTypeSelection}
            updateCell={updateCell}
            isReceivingTranscripts={isReceivingTranscripts}
            setIsReceivingTranscripts={onTranscriptToggle}
            onTranscriptToggle={onTranscriptToggle}
          />
        </section>
      </main>

      {/* Floating Add Shot Controls */}
      <AddShotControls
        config={config}
        rows={rows}
        setRows={setRows}
        setCurrentIndex={setCurrentIndex}
        selectedProjectId={selectedProjectId}
      />

      {/* Floating Bot Status and Transcript Control */}
      <FloatingControls
        botIsActive={botIsActive}
        status={status}
        isReceivingTranscripts={isReceivingTranscripts}
        joinedMeetId={joinedMeetId}
        onTranscriptToggle={onTranscriptToggle}
      />

      <footer className="app-footer">
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
          <span>© {new Date().getFullYear()} Dailies Note Assistant</span>
        </div>
      </footer>
    </div>
  );
}

export default AppLayout;