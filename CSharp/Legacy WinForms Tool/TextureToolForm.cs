using System;
using System.Drawing;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using RageLib.Models;
using RageLib.Textures;

namespace ModelTextureTool
{
    public class TextureToolForm : Form
    {
        private readonly ToolStrip _toolStrip;
        private readonly ToolStripButton _openButton;
        private readonly ToolStripButton _exportButton;
        private readonly ToolStripButton _exportAllButton;
        private readonly ToolStripButton _saveButton;
        private readonly ToolStripButton _saveAsButton;
        private readonly ToolStripLabel _statusLabel;
        private readonly TextureView _textureView;
        private readonly TextureViewController _textureViewController;

        private ModelFile _currentModelFile;
        private TextureFile _currentTextureFile;
        private string _currentPath;
        private string _currentPlatformLabel;
        private bool _hasUnsavedChanges;
        private readonly HashSet<Texture> _modifiedTextures = new HashSet<Texture>();

        public TextureToolForm()
        {
            Text = "Model Texture Tool - GTA IV";
            Width = 1200;
            Height = 800;
            StartPosition = FormStartPosition.CenterScreen;
            AllowDrop = true;

            _toolStrip = new ToolStrip();
            _openButton = new ToolStripButton("Open");
            _exportButton = new ToolStripButton("Export Selected");
            _exportAllButton = new ToolStripButton("Export All");
            _saveButton = new ToolStripButton("Save");
            _saveAsButton = new ToolStripButton("Save As");
            _statusLabel = new ToolStripLabel("Open a PS3 .cdr, PC .wdr or Xbox .xdr file to inspect embedded textures.");

            _toolStrip.Items.Add(_openButton);
            _toolStrip.Items.Add(_exportButton);
            _toolStrip.Items.Add(_exportAllButton);
            _toolStrip.Items.Add(new ToolStripSeparator());
            _toolStrip.Items.Add(_saveButton);
            _toolStrip.Items.Add(_saveAsButton);
            _toolStrip.Items.Add(new ToolStripSeparator());
            _toolStrip.Items.Add(_statusLabel);

            _textureView = new TextureView();
            _textureView.Dock = DockStyle.Fill;

            Controls.Add(_textureView);
            Controls.Add(_toolStrip);

            _textureViewController = new TextureViewController(_textureView);

            _openButton.Click += OpenButton_Click;
            _exportButton.Click += ExportButton_Click;
            _exportAllButton.Click += ExportAllButton_Click;
            _saveButton.Click += SaveButton_Click;
            _saveAsButton.Click += SaveAsButton_Click;
            FormClosed += TextureToolForm_FormClosed;
            FormClosing += TextureToolForm_FormClosing;
            DragEnter += TextureToolForm_DragEnter;
            DragDrop += TextureToolForm_DragDrop;
            _textureView.AllowDrop = true;
            _textureView.DragEnter += TextureToolForm_DragEnter;
            _textureView.DragDrop += TextureToolForm_DragDrop;

            UpdateUiState();
        }

        private void TextureToolForm_FormClosed(object sender, FormClosedEventArgs e)
        {
            DisposeCurrentFile();
        }

        private void OpenButton_Click(object sender, EventArgs e)
        {
            if (!PromptSaveChangesIfNeeded())
            {
                return;
            }

            using (var ofd = new OpenFileDialog())
            {
                ofd.Title = "Open GTA IV Drawable";
                ofd.Filter = "Drawable Files (*.cdr;*.wdr;*.xdr)|*.cdr;*.wdr;*.xdr|All files (*.*)|*.*";
                ofd.CheckFileExists = true;

                if (ofd.ShowDialog(this) == DialogResult.OK)
                {
                    OpenModel(ofd.FileName);
                }
            }
        }

        private void TextureToolForm_DragEnter(object sender, DragEventArgs e)
        {
            if (TryGetDroppedDrawablePath(e.Data) != null)
            {
                e.Effect = DragDropEffects.Copy;
                return;
            }

            e.Effect = DragDropEffects.None;
        }

        private void TextureToolForm_DragDrop(object sender, DragEventArgs e)
        {
            var droppedPath = TryGetDroppedDrawablePath(e.Data);
            if (string.IsNullOrEmpty(droppedPath))
            {
                return;
            }

            if (!PromptSaveChangesIfNeeded())
            {
                return;
            }

            OpenModel(droppedPath);
        }

        private void ExportButton_Click(object sender, EventArgs e)
        {
            var texture = _textureView.SelectedTexture;
            if (texture == null)
            {
                MessageBox.Show(this, "Select a texture before exporting.", "Export Texture",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            using (var sfd = new SaveFileDialog())
            {
                if (texture.IsExternalReference)
                {
                    MessageBox.Show(this, "This entry is only an external texture reference. There is no embedded Xbox surface to export from this .xdr.",
                        "Export Texture", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }

                sfd.Title = "Export Texture";
                sfd.Filter = "DirectDraw Surface (*.dds)|*.dds";
                sfd.AddExtension = true;
                sfd.OverwritePrompt = true;
                sfd.FileName = texture.TitleName + ".dds";

                if (sfd.ShowDialog(this) == DialogResult.OK)
                {
                    DdsCodec.Export(texture, sfd.FileName);
                }
            }
        }

        private void ExportAllButton_Click(object sender, EventArgs e)
        {
            if (_currentTextureFile == null || _currentTextureFile.Count == 0)
            {
                MessageBox.Show(this, "There are no textures available to export.", "Export All",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            using (var folderDialog = new FolderBrowserDialog())
            {
                folderDialog.Description = "Choose the folder where the extracted textures will be saved.";
                if (folderDialog.ShowDialog(this) == DialogResult.OK)
                {
                    foreach (var texture in _currentTextureFile.Textures)
                    {
                        if (texture.IsExternalReference)
                        {
                            continue;
                        }

                        var outputPath = Path.Combine(folderDialog.SelectedPath, texture.TitleName + ".dds");
                        DdsCodec.Export(texture, outputPath);
                    }

                    MessageBox.Show(this, "Textures exported successfully as DDS.", "Export All",
                        MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
            }
        }

        private void OpenModel(string filename)
        {
            DisposeCurrentFile();

            var modelFile = new ModelFile();

            try
            {
                modelFile.Open(filename);
            }
            catch (Exception ex)
            {
                modelFile.Dispose();
                MessageBox.Show(this, ex.Message, "Unable to Open File", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            if (modelFile.EmbeddedTextureFile == null || modelFile.EmbeddedTextureFile.Count == 0)
            {
                modelFile.Dispose();
                MessageBox.Show(this, "No embedded textures were found in this drawable.", "Open Drawable",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            _currentModelFile = modelFile;
            _currentTextureFile = modelFile.EmbeddedTextureFile;
            _currentPath = filename;
            _currentPlatformLabel = GetPlatformLabel(modelFile);

            _textureViewController.TextureFile = _currentTextureFile;
            _hasUnsavedChanges = false;
            _modifiedTextures.Clear();

            UpdateUiState();
        }

        private void DisposeCurrentFile()
        {
            _textureViewController.TextureFile = null;
            _textureView.ClearTextures();

            if (_currentModelFile != null)
            {
                _currentModelFile.Dispose();
                _currentModelFile = null;
            }

            _currentTextureFile = null;
            _currentPath = null;
            _currentPlatformLabel = null;
            _hasUnsavedChanges = false;
            _modifiedTextures.Clear();

            UpdateUiState();
        }

        private void UpdateUiState()
        {
            var hasTextures = _currentTextureFile != null && _currentTextureFile.Count > 0;
            var hasSelectedTexture = hasTextures && _textureView.SelectedTexture != null;
            _exportButton.Enabled = hasTextures;
            _exportAllButton.Enabled = hasTextures;
            _saveButton.Enabled = hasTextures && _hasUnsavedChanges;
            _saveAsButton.Enabled = hasTextures;

            if (hasTextures && !string.IsNullOrEmpty(_currentPath))
            {
                string dirtySuffix = _hasUnsavedChanges ? " [modified]" : string.Empty;
                string platformSuffix = string.IsNullOrEmpty(_currentPlatformLabel) ? string.Empty : " [" + _currentPlatformLabel + "]";
                _statusLabel.Text = Path.GetFileName(_currentPath) + " loaded with " + _currentTextureFile.Count + " texture(s)." + platformSuffix + dirtySuffix;
            }
            else
            {
                _statusLabel.Text = "Open a PS3 .cdr, PC .wdr or Xbox .xdr file to inspect embedded textures.";
            }
        }

        private void SaveButton_Click(object sender, EventArgs e)
        {
            SaveCurrentFile(false);
        }

        private void SaveAsButton_Click(object sender, EventArgs e)
        {
            SaveCurrentFile(true);
        }

        private void SaveCurrentFile(bool saveAs)
        {
            if (_currentModelFile == null || string.IsNullOrEmpty(_currentPath))
            {
                return;
            }

            if (_modifiedTextures.Any(texture => texture.HasUnsupportedPs3WriteLayout))
            {
                MessageBox.Show(this,
                    "One or more modified PS3 textures use a wrapped storage layout that the tool still cannot rebuild safely. Saving now would corrupt the file, so the operation was cancelled.",
                    "Unsupported PS3 Save",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return;
            }

            if (_modifiedTextures.Any(texture => texture.RequiresPs3ReferenceRepair))
            {
                MessageBox.Show(this,
                    "This modified PS3 texture uses a repaired storage layout that the tool still cannot rebuild safely. Saving was cancelled to avoid corrupting the file.",
                    "Unsupported PS3 Save",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return;
            }

            string targetPath = _currentPath;
            if (saveAs)
            {
                using (var sfd = new SaveFileDialog())
                {
                    string extension = Path.GetExtension(_currentPath);
                    sfd.Title = "Save Drawable As";
                    sfd.Filter = "GTA Drawable (*" + extension + ")|*" + extension + "|All files (*.*)|*.*";
                    sfd.AddExtension = true;
                    sfd.OverwritePrompt = true;
                    sfd.FileName = Path.GetFileName(_currentPath);

                    if (sfd.ShowDialog(this) != DialogResult.OK)
                    {
                        return;
                    }

                    targetPath = sfd.FileName;
                }
            }

            try
            {
                _currentModelFile.Save(targetPath);
                _currentPath = targetPath;
                _hasUnsavedChanges = false;
                _modifiedTextures.Clear();
                UpdateUiState();
                MessageBox.Show(this, "Texture changes saved successfully.", "Save",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, ex.Message, "Unable to Save File", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void TextureToolForm_FormClosing(object sender, FormClosingEventArgs e)
        {
            if (!PromptSaveChangesIfNeeded())
            {
                e.Cancel = true;
            }
        }

        private bool PromptSaveChangesIfNeeded()
        {
            if (!_hasUnsavedChanges)
            {
                return true;
            }

            var result = MessageBox.Show(this,
                "There are unsaved texture changes. Do you want to save them before continuing?",
                "Unsaved Changes",
                MessageBoxButtons.YesNoCancel,
                MessageBoxIcon.Question);

            if (result == DialogResult.Cancel)
            {
                return false;
            }

            if (result == DialogResult.Yes)
            {
                SaveCurrentFile(false);
                return !_hasUnsavedChanges;
            }

            return true;
        }

        private static string TryGetDroppedDrawablePath(IDataObject dataObject)
        {
            if (dataObject == null || !dataObject.GetDataPresent(DataFormats.FileDrop))
            {
                return null;
            }

            var files = dataObject.GetData(DataFormats.FileDrop) as string[];
            if (files == null || files.Length == 0)
            {
                return null;
            }

            foreach (var file in files)
            {
                string extension = Path.GetExtension(file);
                if (string.Equals(extension, ".cdr", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(extension, ".wdr", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(extension, ".xdr", StringComparison.OrdinalIgnoreCase))
                {
                    return file;
                }
            }

            return null;
        }

        private static string GetPlatformLabel(ModelFile modelFile)
        {
            if (modelFile == null)
            {
                return null;
            }

            if (modelFile.IsBigEndian)
            {
                return "PS3";
            }

            switch (modelFile.ResourceType)
            {
                case RageLib.Common.Resources.ResourceType.ModelXBOX:
                    return "Xbox";
                case RageLib.Common.Resources.ResourceType.Model:
                case RageLib.Common.Resources.ResourceType.ModelFrag:
                    return "PC";
                default:
                    return "Unknown";
            }
        }
    }
}
