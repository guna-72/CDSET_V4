import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';

/**
 * Exports system logs to a professional PDF document.
 * 
 * @param {Object} options
 * @param {Array} options.logs - Array of log objects ({ time, tag, msg, message, type, output, hint })
 * @param {string} options.selectedRunId - Current run ID (if any)
 * @param {string} options.selectedProjectId - Current project ID
 * @param {string} options.filter - Current log filter ('All', 'Chaos', 'Recovery', 'System')
 * @returns {boolean} Success status
 */
export function exportLogsPdf({ logs = [], selectedRunId = '', selectedProjectId = '', filter = 'All' }) {
  if (!logs || logs.length === 0) {
    alert('No log entries available to export to PDF.');
    return false;
  }

  // Create document in portrait A4
  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'mm',
    format: 'a4',
  });

  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 14;

  // Primary brand colors
  const primaryColor = [79, 70, 229]; // #4f46e5 Indigo
  const textDark = [15, 23, 42];      // #0f172a Slate 900
  const textMuted = [100, 116, 139];  // #64748b Slate 500
  const bgCard = [248, 250, 252];     // #f8fafc Slate 50
  const borderCard = [226, 232, 240]; // #e2e8f0 Slate 200

  // 1. Top Decorative Brand Bar
  doc.setFillColor(...primaryColor);
  doc.rect(0, 0, pageWidth, 4.5, 'F');

  // 2. Header Title & Subtitle
  let currentY = 16;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  doc.setTextColor(...textDark);
  doc.text('System Event & Execution Logs', margin, currentY);

  currentY += 6;
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9.5);
  doc.setTextColor(...textMuted);
  doc.text('Chaos Tutor / CD-SET Resilience Engineering Platform', margin, currentY);

  // 3. Metadata Summary Card
  currentY += 7;
  const cardHeight = 26;
  const cardWidth = pageWidth - margin * 2;

  doc.setFillColor(...bgCard);
  doc.setDrawColor(...borderCard);
  doc.setLineWidth(0.3);
  doc.roundedRect(margin, currentY, cardWidth, cardHeight, 2, 2, 'FD');

  // Summary counts
  const countTotal = logs.length;
  const countErrors = logs.filter(l => l.tag === 'ERROR' || l.tag === 'CHAOS').length;
  const countRecov = logs.filter(l => l.tag === 'RECOV').length;
  const countInfo = logs.filter(l => l.tag === 'INFO').length;

  const col1X = margin + 5;
  const col2X = margin + 65;
  const col3X = margin + 125;
  const row1Y = currentY + 7;
  const row2Y = currentY + 15;
  const row3Y = currentY + 22;

  doc.setFontSize(8.5);

  // Col 1
  doc.setFont('helvetica', 'bold');
  doc.setTextColor(...textDark);
  doc.text('Project: ', col1X, row1Y);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(...textMuted);
  const projDisplay = selectedProjectId ? (selectedProjectId.length > 22 ? selectedProjectId.slice(0, 20) + '…' : selectedProjectId) : 'All Projects';
  doc.text(projDisplay, col1X + 14, row1Y);

  doc.setFont('helvetica', 'bold');
  doc.setTextColor(...textDark);
  doc.text('Run ID: ', col1X, row2Y);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(...textMuted);
  const runDisplay = selectedRunId ? (selectedRunId.length > 20 ? selectedRunId.slice(0, 18) + '…' : selectedRunId) : 'Live Stream / All';
  doc.text(runDisplay, col1X + 14, row2Y);

  // Col 2
  doc.setFont('helvetica', 'bold');
  doc.setTextColor(...textDark);
  doc.text('Filter Applied: ', col2X, row1Y);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(...textMuted);
  doc.text(filter, col2X + 22, row1Y);

  doc.setFont('helvetica', 'bold');
  doc.setTextColor(...textDark);
  doc.text('Export Date: ', col2X, row2Y);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(...textMuted);
  doc.text(new Date().toLocaleDateString() + ' ' + new Date().toLocaleTimeString(), col2X + 20, row2Y);

  // Col 3
  doc.setFont('helvetica', 'bold');
  doc.setTextColor(...textDark);
  doc.text('Total Entries: ', col3X, row1Y);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(...textMuted);
  doc.text(String(countTotal), col3X + 22, row1Y);

  doc.setFont('helvetica', 'bold');
  doc.setTextColor(...textDark);
  doc.text('Breakdown: ', col3X, row2Y);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(...textMuted);
  doc.text(`${countInfo} Info, ${countRecov} Recov, ${countErrors} Chaos/Err`, col3X + 20, row2Y);

  // 4. Log Rows Table
  const tableData = logs.map((l, index) => {
    let msgText = l.msg || l.message || '';
    if (l.hint) {
      msgText += `\n[Explanation] ${l.hint}`;
    }
    if (l.output) {
      msgText += `\n[Captured Output]\n${l.output.trim()}`;
    }
    return [
      String(index + 1),
      l.time || '—',
      `[${l.tag || 'INFO'}]`,
      (l.type || 'system').toUpperCase(),
      msgText
    ];
  });

  autoTable(doc, {
    startY: currentY + cardHeight + 6,
    head: [['#', 'Time', 'Tag', 'Type', 'Event Message & Captured Output']],
    body: tableData,
    margin: { left: margin, right: margin, bottom: 18 },
    styles: {
      font: 'helvetica',
      fontSize: 8,
      cellPadding: 2.8,
      textColor: [30, 41, 59],
      overflow: 'linebreak',
      valign: 'top',
    },
    headStyles: {
      fillColor: [30, 41, 59],
      textColor: [255, 255, 255],
      fontStyle: 'bold',
      fontSize: 8.5,
    },
    alternateRowStyles: {
      fillColor: [248, 250, 252],
    },
    columnStyles: {
      0: { cellWidth: 10, halign: 'center', textColor: [100, 116, 139] },
      1: { cellWidth: 24, fontStyle: 'normal' },
      2: { cellWidth: 20, fontStyle: 'bold', halign: 'center' },
      3: { cellWidth: 22, fontSize: 7.5, textColor: [100, 116, 139] },
      4: { cellWidth: 'auto' },
    },
    didParseCell: (data) => {
      // Highlight tags with appropriate theme colors
      if (data.section === 'body' && data.column.index === 2) {
        const text = String(data.cell.raw || '');
        if (text.includes('ERROR') || text.includes('CHAOS')) {
          data.cell.styles.textColor = [220, 38, 38]; // Red
        } else if (text.includes('WARN')) {
          data.cell.styles.textColor = [217, 119, 6]; // Amber
        } else if (text.includes('RECOV')) {
          data.cell.styles.textColor = [16, 185, 129]; // Emerald
        } else if (text.includes('INFO')) {
          data.cell.styles.textColor = [37, 99, 235]; // Blue
        }
      }
    },
    didDrawPage: (data) => {
      // Footer on every page
      const pageNumber = data.pageNumber;
      const totalPages = doc.internal.getNumberOfPages();

      doc.setDrawColor(226, 232, 240);
      doc.setLineWidth(0.2);
      doc.line(margin, pageHeight - 12, pageWidth - margin, pageHeight - 12);

      doc.setFontSize(7.5);
      doc.setFont('helvetica', 'normal');
      doc.setTextColor(148, 163, 184);
      doc.text('CD-SET Platform • System Verification & Resilience Logs', margin, pageHeight - 7);

      const pageStr = `Page ${pageNumber} of ${totalPages}`;
      doc.text(pageStr, pageWidth - margin - doc.getTextWidth(pageStr), pageHeight - 7);
    }
  });

  // Calculate clean filename
  const cleanId = (selectedRunId || selectedProjectId || 'system-logs').replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 24);
  const fileName = `cdset-logs-${cleanId}.pdf`;

  // Trigger browser download
  doc.save(fileName);
  return true;
}
