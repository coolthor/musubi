---
title: "React Server Components: Three Gotchas That Cost Me a Day"
date: "2026-02-15"
tags: ["react", "next.js", "typescript", "debugging"]
---

## Gotcha 1: useState in Server Components

Server Components can't use React hooks. The error message is clear,
but the fix isn't always obvious — sometimes you need to extract a
small Client Component wrapper just for the interactive part.

## Gotcha 2: Dynamic imports break streaming

Using `next/dynamic` with `ssr: false` in a Server Component layout
defeats the purpose of streaming. The entire page waits for the dynamic
chunk. Use React's built-in `Suspense` boundaries instead.

## Gotcha 3: Serialization boundary

Props passed from Server → Client components must be serializable.
No functions, no class instances, no Dates. Convert to ISO strings
before crossing the boundary.

## Lesson

RSC is a different mental model from traditional React. Don't fight
it — restructure components around the server/client boundary instead
of trying to make old patterns work.
