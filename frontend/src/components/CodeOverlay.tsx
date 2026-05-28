import {
  BoundingBox,
  type BoundingBoxProps,
  type BoundingBoxType,
  computeBoundingBoxStyle,
  DocumentContext,
  HighlightOverlay,
  TransformContext,
} from '@allenai/pdf-components';
import { SlArrowLeft, SlArrowRight } from "react-icons/sl";


import * as React from 'react';
import { createPortal } from 'react-dom';
import { useSidePanel } from '../context/SidePanelContext.tsx';

/** Geometry matches `BoundingBox`; `tooltip` is shown on hover (native + optional floating). */
export type BoundingBoxWithTooltip = BoundingBoxType & {
  file_infos: string[];
  description: string;
  code_snippets: {
    content: string;
    filepath: string;
    start_line: number;
    end_line: number;
  }[];
  hitKey: string;
  /** Default `overlay` (filled highlight). `underline` draws a line under the section only. */
  variant?: 'overlay' | 'underline';
};

type overlayProps = {
  pageIndex: number;
  boxes: Array<BoundingBoxWithTooltip>;
};

/**
 * Invisible hit target on top of the page overlay. `HighlightOverlay` only uses BoundingBox
 * props for SVG mask geometry — it does not mount DOM nodes, so there is nothing to hover
 * unless we add a separate layer like this.
 */
function PdfBoundingHitTarget({
  box,
  pageIndex,
}: {
  box: BoundingBoxWithTooltip;
  pageIndex: number;
}) {
  const { pageDimensions } = React.useContext(DocumentContext);
  const { rotation, scale } = React.useContext(TransformContext);
  const [floating, setFloating] = React.useState<{ x: number; y: number } | null>(null);
  const [hover, setHover] = React.useState(false);
  const leaveTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const { showCode } = useSidePanel();

  const [codeIndex, setCodeIndex] = React.useState(0);

  if (box.page !== pageIndex) {
    return null;
  }

  const showAllSnippetsForSelectedFile = (codeSnippets: typeof box.code_snippets, index: number) => {
    console.log('showAllSnippetsForSelectedFile', codeSnippets, index);
    const s = codeSnippets[index];
    if (!s) return;
    const thisFilePath = s.filepath;
    const forFile = codeSnippets.filter((t) => t.filepath === thisFilePath);
    showCode({
      filePath: thisFilePath,
      codeRanges: forFile.map((t) => ({ startLine: t.start_line, endLine: t.end_line })),
      scrollToRange: { startLine: s.start_line, endLine: s.end_line },
      description: box.description || '',
    });
  };
  const { top, left, width, height } = computeBoundingBoxStyle(
    { top: box.top, left: box.left, width: box.width, height: box.height },
    pageDimensions,
    rotation,
    scale,
  );

  const style: React.CSSProperties = {
    position: 'absolute',
    top,
    left,
    width,
    height,
    zIndex: 2,
    boxSizing: 'content-box',
    opacity: hover ? 0.5 : 0.25,
    outline: hover ? '2px solid rgba(0, 180, 255, 0.85)' : 'none',
    backgroundColor: hover ? 'rgba(0, 160, 255, 0.25)' : 'orange',
    cursor: 'pointer',
    pointerEvents: 'auto',
    transition: 'opacity 80ms ease',
  };

  const tooltipNode =
    floating &&
    createPortal(
      <div
        className="pdf-hit-tooltip"
        style={{
          position: 'fixed',
          left: floating.x,
          top: floating.y,
          zIndex: 10000,
          maxWidth: 520,
          padding: '8px 10px',
          fontSize: 12,
          lineHeight: 1.35,
          background: 'rgba(20, 20, 24, 0.95)',
          color: '#f4f4f5',
          borderRadius: 6,
          boxShadow: '0 4px 24px rgba(0,0,0,0.35)',
          pointerEvents: 'auto',
          whiteSpace: 'pre-wrap',
        }}
        onMouseEnter={() => {
          if (leaveTimer.current) clearTimeout(leaveTimer.current);
        }}
        onMouseLeave={() => {
          setHover(false);
          setFloating(null);
        }}
      >
        <div className="pdf-hit-tooltip__description">{box.description}</div>
        {box.code_snippets.length > 0 && (
          <div className="pdf-hit-tooltip__path">{box.file_infos[codeIndex]}</div>
        )}
        {box.code_snippets.length > 0 && (
        <div className="pdf-hit-tooltip__actions">
          {box.code_snippets.length > 1 ? (
            <button
              type="button"
              className="pdf-hit-tooltip__icon-btn"
              aria-label="Previous code snippet"
              onClick={() =>
                setCodeIndex((codeIndex - 1 + box.code_snippets.length) % box.code_snippets.length)
              }
            >
              <SlArrowLeft />
            </button>
          ) : (
            <span className="pdf-hit-tooltip__icon-spacer" aria-hidden />
          )}
          <button
            type="button"
            className="pdf-hit-tooltip__text-btn"
            onClick={() => showAllSnippetsForSelectedFile(box.code_snippets, codeIndex)}
          >
            View code
          </button>
          {box.code_snippets.length > 1 ? (
            <button
              type="button"
              className="pdf-hit-tooltip__icon-btn"
              aria-label="Next code snippet"
              onClick={() => setCodeIndex((codeIndex + 1) % box.code_snippets.length)}
            >
              <SlArrowRight />
            </button>
          ) : (
            <span className="pdf-hit-tooltip__icon-spacer" aria-hidden />
          )}
        </div>
        )}
      </div>,
      document.body,
    );

  return (
    <>
      <div
        style={style}
        role="button"
        tabIndex={0}
        onMouseEnter={(e) => {
          if (leaveTimer.current) clearTimeout(leaveTimer.current);
          setHover(true);
          setFloating(prev => prev ?? { x: e.clientX + 12, y: e.clientY + 12 });
        }}
        onMouseLeave={() => {
          leaveTimer.current = setTimeout(() => {
            setHover(false);
            setFloating(null);
          }, 150);
        }}
      />
      {tooltipNode}
    </>
  );
}

const UNDERLINE_THICKNESS_PX = 3;

/**
 * Section mapping from code→paper: a bottom underline instead of a filled overlay.
 */
function PdfUnderlineHitTarget({
  box,
  pageIndex,
}: {
  box: BoundingBoxWithTooltip;
  pageIndex: number;
}) {
  const { pageDimensions } = React.useContext(DocumentContext);
  const { rotation, scale } = React.useContext(TransformContext);
  const [floating, setFloating] = React.useState<{ x: number; y: number } | null>(null);
  const [hover, setHover] = React.useState(false);
  const leaveTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  if (box.page !== pageIndex) {
    return null;
  }

  const { top, left, width, height } = computeBoundingBoxStyle(
    { top: box.top, left: box.left, width: box.width, height: box.height },
    pageDimensions,
    rotation,
    scale,
  );

  const hitStyle: React.CSSProperties = {
    position: 'absolute',
    top,
    left,
    width,
    height,
    zIndex: 2,
    boxSizing: 'border-box',
    backgroundColor: 'transparent',
    cursor: 'pointer',
    pointerEvents: 'auto',
  };

  const underlineStyle: React.CSSProperties = {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    height: hover ? UNDERLINE_THICKNESS_PX + 1 : UNDERLINE_THICKNESS_PX,
    backgroundColor: hover ? 'rgba(37, 99, 235, 0.95)' : 'rgba(37, 99, 235, 0.75)',
    borderRadius: 1,
    pointerEvents: 'none',
  };

  const tooltipNode =
    floating &&
    createPortal(
      <div
        className="pdf-hit-tooltip"
        style={{
          position: 'fixed',
          left: floating.x,
          top: floating.y,
          zIndex: 10000,
          maxWidth: 520,
          padding: '8px 10px',
          fontSize: 12,
          lineHeight: 1.35,
          background: 'rgba(20, 20, 24, 0.95)',
          color: '#f4f4f5',
          borderRadius: 6,
          boxShadow: '0 4px 24px rgba(0,0,0,0.35)',
          pointerEvents: 'auto',
          whiteSpace: 'pre-wrap',
        }}
        onMouseEnter={() => {
          if (leaveTimer.current) clearTimeout(leaveTimer.current);
        }}
        onMouseLeave={() => {
          setHover(false);
          setFloating(null);
        }}
      >
        <div className="pdf-hit-tooltip__description">{box.description}</div>
      </div>,
      document.body,
    );

  return (
    <>
      <div
        className="pdf-section-underline-hit"
        style={hitStyle}
        role="button"
        tabIndex={0}
        onMouseEnter={(e) => {
          if (leaveTimer.current) clearTimeout(leaveTimer.current);
          setHover(true);
          setFloating((prev) => prev ?? { x: e.clientX + 12, y: e.clientY + 12 });
        }}
        onMouseLeave={() => {
          leaveTimer.current = setTimeout(() => {
            setHover(false);
            setFloating(null);
          }, 150);
        }}
      >
        <div className="pdf-section-underline" style={underlineStyle} aria-hidden />
      </div>
      {tooltipNode}
    </>
  );
}

function maskBoundingBoxes(
  pageIndex: number,
  boxes: Array<BoundingBoxWithTooltip>,
): Array<React.ReactElement<BoundingBoxProps>> {
  const out: Array<React.ReactElement<BoundingBoxProps>> = [];
  boxes.forEach((box) => {
    if (box.page !== pageIndex) return;
    out.push(
      <BoundingBox
        key={`mask-${box.hitKey}`}
        page={box.page}
        top={box.top}
        left={box.left}
        width={box.width}
        height={box.height}
        className="reader__sample-highlight-overlay__bbox"
      />,
    );
  });
  return out;
}

/**
 * Mask cutouts (HighlightOverlay) + separate invisible hit targets for hover tooltips.
 */
export const HighlightOverlayDemo: React.FunctionComponent<overlayProps> = ({
  pageIndex,
  boxes,
}) => {
  const overlayBoxes = boxes.filter((box) => box.variant !== 'underline');
  const underlineBoxes = boxes.filter((box) => box.variant === 'underline');

  return (
    <>
      {overlayBoxes.length > 0 && (
        <HighlightOverlay pageIndex={pageIndex}>
          {maskBoundingBoxes(pageIndex, overlayBoxes)}
        </HighlightOverlay>
      )}
      {overlayBoxes.map((box) => (
        <PdfBoundingHitTarget key={`hit-${box.hitKey}`} box={box} pageIndex={pageIndex} />
      ))}
      {underlineBoxes.map((box) => (
        <PdfUnderlineHitTarget key={`underline-${box.hitKey}`} box={box} pageIndex={pageIndex} />
      ))}
    </>
  );
};
