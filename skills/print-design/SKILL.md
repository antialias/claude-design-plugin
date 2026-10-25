---
name: print-design
description: Design and refine documents for paper, including worksheets, forms, handouts, posters and printed PDFs. Use when physical layout, typography, pagination or space for handwriting matters. Screen interfaces use the separate ui-concept skill.
---

# Print design

Design for the person holding the page: what they need to find, read, compare,
mark or write. The finished page should have a clear hierarchy, deliberate
spacing and enough room for its actual use.

## Work in the physical medium

Use the task's page size, orientation, printing method, audience and content
requirements. Reuse known requirements rather than asking for them again.
An existing template is a useful starting point; adapt its composition when
the content calls for it, within the project's actual constraints.

Judge type, line lengths, margins, diagrams and writing areas at the intended
physical size. A page that looks readable when enlarged on screen may be too
small in print. Allow for printer margins, binding or duplex use when relevant;
use bleed only for a production process that supports it. Color should survive
the intended printer, including grayscale when that is how it will be used.

Let the information and the task determine the layout. Lists, columns, tables,
illustrations and separate pages each suit different reading patterns. When
content does not fit, reconsider the composition before shrinking everything.
Preserve required meaning and identifiers while changing presentation. A genuine
conflict among content, readability and page limits belongs to the project's
decision process.

## Make the document the draft

Work in the available editable format and render it with the project's toolchain.
The rendered document can serve as the design draft; a separate generated mockup
is optional. Keep text and structural elements editable rather than flattening
the whole page into an image. Use the sibling `design:imagegen` skill when a
generated illustration or visual exploration would help, retaining sufficient
resolution for its placed size.

Approval requirements come from the user and the project workflow. This skill
does not add a separate approval gate or assume that approval to design also
authorizes publishing or printing.

## Inspect the actual output

Render and inspect every final page at its intended size. Check hierarchy,
readability, alignment, clipping, awkward wraps and breaks, and space for marks
or handwriting. Check the complete document as well as its densest page; a
successful render alone does not establish that the design works. Repair and
re-render the affected pages, then inspect the final export.

For interactive-looking elements on paper, make their physical purpose clear:
a checkbox needs marking room, and a printed link needs a usable printed form.
Verify any QR codes against their destinations when present. Deliver the editable
source and print-ready output through the project's existing artifact workflow.
