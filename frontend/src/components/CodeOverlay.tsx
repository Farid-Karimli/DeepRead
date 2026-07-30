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
import ShikiHighlighter from 'react-shiki';

import * as React from 'react';
import { createPortal } from 'react-dom';
import { useSidePanel } from '../context/SidePanelContext.tsx';
import {
  copilotContextRefKey,
  useCopilotContext,
} from '../context/CopilotContext.tsx';
import { useTheme } from '../context/ThemeContext';
import { getShikiLanguage } from '../utils/codeLanguage';
import type { CopilotContextRef } from '../api/types.ts';

/** First N lines of a snippet shown in the tooltip preview, to keep it glanceable. */
const TOOLTIP_PREVIEW_LINE_COUNT = 6;

function previewExcerpt(content: string | undefined): string {
  if (!content) return '';
  return content.split('\n').slice(0, TOOLTIP_PREVIEW_LINE_COUNT).join('\n');
}

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
  color?: string;
  content_type?: string;
  /** Canonical reference attached to the next Copilot message on request. */
  contextRef?: CopilotContextRef;
};

type overlayProps = {
  pageIndex: number;
  boxes: Array<BoundingBoxWithTooltip>;
};

type AiOverlapRegion = BoundingBoxType & {
  overlapKey: string;
};

function isAiDrivenBox(box: BoundingBoxWithTooltip): boolean {
  return (
    box.contextRef?.type === 'mapping' &&
    box.contextRef.mapping_type === 'initial_analysis'
  );
}

/**
 * Return disjoint rectangles covered by at least two AI matches. Splitting the
 * page into boundary-aligned cells avoids stacking pairwise intersection
 * markers (and accidentally making triple-overlap regions progressively darker).
 */
function findAiOverlapRegions(
  pageIndex: number,
  boxes: Array<BoundingBoxWithTooltip>,
): AiOverlapRegion[] {
  const aiBoxes = boxes.filter(
    (box) =>
      box.page === pageIndex &&
      isAiDrivenBox(box) &&
      box.width > 0 &&
      box.height > 0,
  );
  if (aiBoxes.length < 2) {
    return [];
  }

  const xBoundaries = Array.from(
    new Set(aiBoxes.flatMap((box) => [box.left, box.left + box.width])),
  ).sort((a, b) => a - b);
  const regions: AiOverlapRegion[] = [];

  for (let xIndex = 0; xIndex < xBoundaries.length - 1; xIndex += 1) {
    const left = xBoundaries[xIndex];
    const right = xBoundaries[xIndex + 1];
    if (right <= left) continue;

    const xMidpoint = left + (right - left) / 2;
    const boxesInStrip = aiBoxes.filter(
      (box) => xMidpoint > box.left && xMidpoint < box.left + box.width,
    );
    if (boxesInStrip.length < 2) continue;

    const yBoundaries = Array.from(
      new Set(boxesInStrip.flatMap((box) => [box.top, box.top + box.height])),
    ).sort((a, b) => a - b);
    const stripIntervals: Array<{ top: number; bottom: number }> = [];

    for (let yIndex = 0; yIndex < yBoundaries.length - 1; yIndex += 1) {
      const top = yBoundaries[yIndex];
      const bottom = yBoundaries[yIndex + 1];
      if (bottom <= top) continue;

      const yMidpoint = top + (bottom - top) / 2;
      const overlapCount = boxesInStrip.filter(
        (box) => yMidpoint > box.top && yMidpoint < box.top + box.height,
      ).length;
      if (overlapCount < 2) continue;

      const previous = stripIntervals.at(-1);
      if (previous?.bottom === top) {
        previous.bottom = bottom;
      } else {
        stripIntervals.push({ top, bottom });
      }
    }

    for (const interval of stripIntervals) {
      const previousStrip = regions.find(
        (region) =>
          region.left + region.width === left &&
          region.top === interval.top &&
          region.top + region.height === interval.bottom,
      );
      if (previousStrip) {
        previousStrip.width = right - previousStrip.left;
        continue;
      }

      regions.push({
        page: pageIndex,
        top: interval.top,
        left,
        width: right - left,
        height: interval.bottom - interval.top,
        overlapKey: `${left}:${interval.top}:${right}:${interval.bottom}`,
      });
    }
  }

  return regions;
}

function PdfAiOverlapMarker({
  region,
  pageIndex,
}: {
  region: AiOverlapRegion;
  pageIndex: number;
}) {
  const { pageDimensions } = React.useContext(DocumentContext);
  const { rotation, scale } = React.useContext(TransformContext);

  if (region.page !== pageIndex) {
    return null;
  }

  const { top, left, width, height } = computeBoundingBoxStyle(
    region,
    pageDimensions,
    rotation,
    scale,
  );

  return (
    <div
      className="pdf-ai-overlap-marker"
      style={{ position: 'absolute', top, left, width, height, zIndex: 3 }}
      aria-hidden="true"
    />
  );
}

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
  const { contextRefs, addContext } = useCopilotContext();
  const { resolvedTheme } = useTheme();

  const [codeIndex, setCodeIndex] = React.useState(0);
  const isContextAttached = box.contextRef
    ? contextRefs.some(
        (ref) => copilotContextRefKey(ref) === copilotContextRefKey(box.contextRef!),
      )
    : false;

  if (box.page !== pageIndex) {
    return null;
  }

  const showAllSnippetsForSelectedFile = (codeSnippets: typeof box.code_snippets, index: number) => {
    const s = codeSnippets[index];
    if (!s) return;
    const thisFilePath = s.filepath;
    const forFile = codeSnippets.filter((t) => t.filepath === thisFilePath);
    showCode({
      filePath: thisFilePath,
      codeRanges: forFile.map((t) => ({ startLine: t.start_line, endLine: t.end_line })),
      scrollToRange: { startLine: s.start_line, endLine: s.end_line },
      paperPageIndex: box.page,
      description: box.description || '',
      candidates: codeSnippets.map((snippet) => ({
        filePath: snippet.filepath,
        startLine: snippet.start_line,
        endLine: snippet.end_line,
      })),
      activeCandidateIndex: index,
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
    backgroundColor: withAlpha(box.color, hover ? UNDERLINE_HOVER_ALPHA : UNDERLINE_ALPHA),
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
        {box.description && (
          <div className="pdf-hit-tooltip__description">
            <span className="pdf-hit-tooltip__description-label">Why this matches</span>
            {box.description}
          </div>
        )}
        {box.code_snippets.length > 0 && (
          <div className="pdf-hit-tooltip__path">{box.file_infos[codeIndex]}</div>
        )}
        {box.code_snippets.length > 0 && (
          <div className="pdf-hit-tooltip__preview">
            <ShikiHighlighter
              theme={resolvedTheme === 'dark' ? 'github-dark' : 'github-light'}
              language={getShikiLanguage(box.code_snippets[codeIndex]?.filepath)}
              showLineNumbers={false}
            >
              {previewExcerpt(box.code_snippets[codeIndex]?.content)}
            </ShikiHighlighter>
          </div>
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
        {box.code_snippets.length > 1 && (
          <div className="pdf-hit-tooltip__counter">
            {codeIndex + 1} / {box.code_snippets.length}
          </div>
        )}
        {box.contextRef && (
          <div className="pdf-hit-tooltip__actions">
            <button
              type="button"
              className="pdf-hit-tooltip__text-btn"
              aria-pressed={isContextAttached}
              disabled={isContextAttached}
              onClick={() => addContext(box.contextRef!)}
            >
              {isContextAttached ? 'Added to chat' : 'Add to chat'}
            </button>
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
const UNDERLINE_TOP_GAP_PX = 3;
const UNDERLINE_ALPHA = 0.6;
const UNDERLINE_HOVER_ALPHA = 1;

/** Override the alpha channel of an rgb()/rgba() color string. Returns the input unchanged if it can't be parsed. */
function withAlpha(color: string | undefined, alpha: number): string | undefined {
  if (!color) {
    return color;
  }
  const match = color.match(
    /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+\s*)?\)$/i,
  );
  if (!match) {
    return color;
  }
  const [, r, g, b] = match;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

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
  const { contextRefs, addContext } = useCopilotContext();

  if (box.page !== pageIndex) {
    return null;
  }

  const isContextAttached = box.contextRef
    ? contextRefs.some(
        (ref) => copilotContextRefKey(ref) === copilotContextRefKey(box.contextRef!),
      )
    : false;

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
    height: height + UNDERLINE_TOP_GAP_PX,
    zIndex: 2,
    boxSizing: 'border-box',
    pointerEvents: 'none',
  };

  const lineHeight = hover ? UNDERLINE_THICKNESS_PX + 1 : UNDERLINE_THICKNESS_PX;
  const underlineStyle: React.CSSProperties = {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    height: UNDERLINE_TOP_GAP_PX + lineHeight,
    boxSizing: 'border-box',
    paddingTop: UNDERLINE_TOP_GAP_PX,
    borderBottom: `${lineHeight}px solid ${withAlpha(box.color, hover ? UNDERLINE_HOVER_ALPHA : UNDERLINE_ALPHA)}`,
    borderRadius: 1,
    cursor: 'pointer',
    pointerEvents: 'auto',
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
        <div className="pdf-hit-tooltip__description">
          {box.content_type ? `[${box.content_type}] ` : ''}
          {box.description}
        </div>
        {box.contextRef && (
          <div className="pdf-hit-tooltip__actions">
            <button
              type="button"
              className="pdf-hit-tooltip__text-btn"
              aria-pressed={isContextAttached}
              disabled={isContextAttached}
              onClick={() => addContext(box.contextRef!)}
            >
              {isContextAttached ? 'Added to chat' : 'Add to chat'}
            </button>
          </div>
        )}
      </div>,
      document.body,
    );

  return (
    <>
      <div className="pdf-section-underline-hit" style={hitStyle}>
        <div
          className="pdf-section-underline"
          style={underlineStyle}
          role="button"
          tabIndex={0}
          aria-label={box.description}
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
        />
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
  const aiOverlapRegions = findAiOverlapRegions(pageIndex, overlayBoxes);

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
      {aiOverlapRegions.map((region) => (
        <PdfAiOverlapMarker
          key={`ai-overlap-${region.overlapKey}`}
          region={region}
          pageIndex={pageIndex}
        />
      ))}
      {underlineBoxes.map((box) => (
        <PdfUnderlineHitTarget key={`underline-${box.hitKey}`} box={box} pageIndex={pageIndex} />
      ))}
    </>
  );
};
