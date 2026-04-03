package com.example.app.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import com.example.app.R

/**
 * Custom star rating bar supporting half-star precision.
 * Supports 1–5 stars, selectable by tapping or dragging.
 */
class RatingBarView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    var rating: Float = 0f
        set(value) {
            field = value.coerceIn(0f, maxStars.toFloat())
            invalidate()
            onRatingChanged?.invoke(field)
        }

    var maxStars: Int = 5
        set(value) {
            field = value
            invalidate()
        }

    var starSize: Float = 48f
        set(value) {
            field = value
            invalidate()
        }

    var starSpacing: Float = 8f
        set(value) {
            field = value
            invalidate()
        }

    var allowHalfStars: Boolean = true

    var onRatingChanged: ((Float) -> Unit)? = null

    private val filledPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFFFFB300.toInt() // amber
        style = Paint.Style.FILL
    }

    private val emptyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFFDDDDDD.toInt()
        style = Paint.Style.FILL
    }

    init {
        attrs?.let {
            val ta = context.obtainStyledAttributes(it, R.styleable.RatingBarView)
            rating = ta.getFloat(R.styleable.RatingBarView_rating, 0f)
            maxStars = ta.getInt(R.styleable.RatingBarView_maxStars, 5)
            starSize = ta.getDimension(R.styleable.RatingBarView_starSize, 48f)
            starSpacing = ta.getDimension(R.styleable.RatingBarView_starSpacing, 8f)
            allowHalfStars = ta.getBoolean(R.styleable.RatingBarView_allowHalfStars, true)
            ta.recycle()
        }
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val width = (maxStars * (starSize + starSpacing) - starSpacing).toInt()
        val height = starSize.toInt()
        setMeasuredDimension(
            resolveSize(width, widthMeasureSpec),
            resolveSize(height, heightMeasureSpec)
        )
    }

    override fun onDraw(canvas: Canvas) {
        for (i in 0 until maxStars) {
            val x = i * (starSize + starSpacing)
            val fillFraction = (rating - i).coerceIn(0f, 1f)
            drawStar(canvas, x, 0f, fillFraction)
        }
    }

    private fun drawStar(canvas: Canvas, x: Float, y: Float, fillFraction: Float) {
        val path = buildStarPath(x + starSize / 2, y + starSize / 2, starSize / 2, starSize / 4)
        canvas.drawPath(path, emptyPaint)
        if (fillFraction > 0f) {
            canvas.save()
            canvas.clipRect(x, y, x + starSize * fillFraction, y + starSize)
            canvas.drawPath(path, filledPaint)
            canvas.restore()
        }
    }

    private fun buildStarPath(cx: Float, cy: Float, outerR: Float, innerR: Float): Path {
        val path = Path()
        val points = 5
        for (i in 0 until points * 2) {
            val angle = Math.PI * i / points - Math.PI / 2
            val r = if (i % 2 == 0) outerR else innerR
            val px = cx + (r * Math.cos(angle)).toFloat()
            val py = cy + (r * Math.sin(angle)).toFloat()
            if (i == 0) path.moveTo(px, py) else path.lineTo(px, py)
        }
        path.close()
        return path
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (!isEnabled) return false
        when (event.action) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                val newRating = (event.x / (starSize + starSpacing))
                    .coerceIn(0f, maxStars.toFloat())
                rating = if (allowHalfStars) (newRating * 2).toInt() / 2f else newRating.toInt().toFloat()
                return true
            }
        }
        return super.onTouchEvent(event)
    }
}
